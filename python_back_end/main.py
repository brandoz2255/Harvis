from fastapi import FastAPI, HTTPException, Request, UploadFile, File, WebSocket, Depends, Form
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.websockets import WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn, os, sys, tempfile, uuid, base64, io, logging, re, requests, random

# Import optimized auth module
from auth_optimized import get_current_user_optimized, auth_optimizer, get_auth_stats

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # Will log after logger is set up
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
import asyncpg
from gemini_api import query_gemini, is_gemini_configured
from typing import List, Optional, Dict, Any, Union
from vison_models.llm_connector import query_qwen, query_llm, load_qwen_model, unload_qwen_model

# Import vibecoding routers
from vibecoding import sessions_router, models_router, execution_router, files_router, commands_router, containers_router
from vibecoding.core import initialize_vibe_agent

from pydantic import BaseModel
import torch, soundfile as sf
import whisper  # Import Whisper

# ─── Authentication Setup ──────────────────────────────────────────────────────
SECRET_KEY = os.getenv("JWT_SECRET", "key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Temporary logging to verify JWT secret is loaded
print(f"Backend JWT_SECRET loaded: {SECRET_KEY[:10]}... Length: {len(SECRET_KEY)}")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

# Database connection
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")

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

# Removed get_db_connection() - using connection pool instead

async def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    logger.info(f"get_current_user called with credentials: {credentials}")
    token = request.cookies.get("access_token")
    if token is None and credentials is not None:
        token = credentials.credentials

    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if token is None:
        logger.error("No credentials provided in cookies or headers")
        raise credentials_exception
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        logger.info(f"JWT payload: {payload}")
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id: int = int(user_id_str)
        logger.info(f"User ID from token: {user_id}")
    except (JWTError, ValueError) as e:
        logger.error(f"JWT decode error: {e}")
        raise credentials_exception
    
    # Use connection pool instead of individual connections
    pool = getattr(request.app.state, 'pg_pool', None)
    if pool:
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT id, username, email, avatar FROM users WHERE id = $1", user_id)
            if user is None:
                logger.error(f"User not found for ID: {user_id}")
                raise credentials_exception
            logger.info(f"User found: {dict(user)}")
            return UserResponse(**dict(user))
    else:
        # Fallback to direct connection if pool unavailable
        logger.warning("Connection pool unavailable, using direct connection")
        conn = await asyncpg.connect(DATABASE_URL, timeout=10)
        try:
            user = await conn.fetchrow("SELECT id, username, email, avatar FROM users WHERE id = $1", user_id)
            if user is None:
                logger.error(f"User not found for ID: {user_id}")
                raise credentials_exception
            logger.info(f"User found: {dict(user)}")
            return UserResponse(**dict(user))
        finally:
            await conn.close()

# ─── Model Management -----------------------------------------------------------
from model_manager import (
    unload_models, unload_all_models, reload_models_if_needed, log_gpu_memory,
    get_tts_model, get_whisper_model, generate_speech, wait_for_vram,
    transcribe_with_whisper_optimized, generate_speech_optimized,
    unload_tts_model, unload_whisper_model
)
from chat_history_module import (
    ChatHistoryManager, ChatMessage, ChatSession, CreateSessionRequest, 
    CreateMessageRequest, MessageHistoryResponse, SessionListResponse,
    SessionNotFoundError, ChatHistoryError
)
from uuid import UUID
import logging
import time

# Vibe agent is now handled in vibecoding.core module

# ─── n8n Automation Setup ─────────────────────────────────────────────────────
from n8n import N8nClient, WorkflowBuilder, N8nAutomationService, N8nStorage
from n8n.models import (
    CreateWorkflowRequest, N8nAutomationRequest, WorkflowExecutionRequest,
    WorkflowResponse
)

# ─── Set up logging ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Reduce uvicorn access log verbosity
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# Log environment loading status
try:
    import dotenv
    logger.info("✅ Successfully loaded environment variables from .env file")
except ImportError:
    logger.warning("⚠️ python-dotenv not installed, environment variables must be passed via Docker")

# ─── Initialize vibe agent ─────────────────────────────────────────────────────
# Vibe agent initialization moved to vibecoding.core module
initialize_vibe_agent(project_dir=os.getcwd())

# ─── Initialize n8n services ──────────────────────────────────────────────────
n8n_client = None
n8n_automation_service = None
n8n_storage = None

def initialize_n8n_services():
    """Initialize n8n services with database pool"""
    global n8n_client, n8n_automation_service, n8n_storage
    try:
        # Debug environment variables
        logger.info(f"N8N_URL: {os.getenv('N8N_URL', 'NOT SET')}")
        logger.info(f"N8N_USER: {os.getenv('N8N_USER', 'NOT SET')}")
        logger.info(f"N8N_PASSWORD: {os.getenv('N8N_PASSWORD', 'NOT SET')}")
        logger.info(f"N8N_API_KEY: {os.getenv('N8N_API_KEY', 'NOT SET')[:20]}..." if os.getenv('N8N_API_KEY') else "N8N_API_KEY: NOT SET")
        
        # Initialize n8n client
        n8n_client = N8nClient()
        
        # Initialize workflow builder
        workflow_builder = WorkflowBuilder()
        
        # Initialize storage (will be properly set up in startup event)
        n8n_storage = None  # Will be set in startup event with db_pool
        
        # Initialize automation service (will be properly set up in startup event)
        n8n_automation_service = None  # Will be set in startup event
        
        logger.info("✅ n8n services initialized successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to initialize n8n services: {e}")
        return False

# Try to initialize n8n services (will be completed in startup event)
initialize_n8n_services()

# ─── Additional logging setup ──────────────────────────────────────────────────
if 'logger' not in locals():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    # Reduce uvicorn access log verbosity
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# ─── Paths ---------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "front_end")
HARVIS_VOICE_PATH = os.path.abspath(
    "harvis_voice.mp3"
)  # Point to the file in project root

# ─── Database Connection Pool -------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create connection pool
    global db_pool, chat_history_manager, n8n_storage, n8n_automation_service, n8n_ai_agent
    try:
        # Fix database hostname: use pgsql-db instead of pgsql
        database_url = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")
        app.state.pg_pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=1, 
            max_size=10,
            command_timeout=30,  # Increased from 5 to 30 seconds
        )
        db_pool = app.state.pg_pool
        logger.info("✅ Database connection pool created")
        
        # Initialize session database
        from vibecoding.db_session import init_session_db
        await init_session_db(app.state.pg_pool)
        
        # Initialize chat history manager
        chat_history_manager = ChatHistoryManager(app.state.pg_pool)
        logger.info("✅ ChatHistoryManager initialized in lifespan")
        
        # Initialize Whisper cache for offline operation
        try:
            from init_whisper_cache import init_whisper_cache
            init_whisper_cache()
            logger.info("✅ Whisper cache initialized for offline operation")
        except Exception as e:
            logger.warning(f"⚠️ Whisper cache initialization failed: {e}")
            logger.info("🔄 Whisper will fall back to online downloads")
        
        # Initialize vibe files database table
        try:
            from vibecoding.files import ensure_vibe_files_table
            await ensure_vibe_files_table()
            logger.info("✅ Vibe files database table initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize vibe files table: {e}")

        # Initialize n8n services with database pool
        if n8n_client:
            n8n_storage = N8nStorage(db_pool)
            await n8n_storage.ensure_tables()
            
            workflow_builder = WorkflowBuilder()
            n8n_automation_service = N8nAutomationService(
                n8n_client=n8n_client,
                workflow_builder=workflow_builder,
                storage=n8n_storage,
                ollama_url=OLLAMA_URL
            )
            logger.info("✅ n8n automation service fully initialized")
            
            # Initialize AI agent with vector database
            try:
                from n8n import initialize_ai_agent
                n8n_ai_agent = await initialize_ai_agent(n8n_automation_service)
                logger.info("✅ n8n AI agent with vector database initialized")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize n8n AI agent: {e}")
                logger.warning("n8n automation will work without vector database enhancement")
        
        logger.info("Database pool and all services initialized successfully")
        
    except Exception as e:
        logger.error(f"❌ Failed to create database pool or initialize n8n services: {e}")
        # Continue without pool - will fall back to direct connections
        app.state.pg_pool = None
    
    yield
    
    # Shutdown: close connection pool
    if hasattr(app.state, 'pg_pool') and app.state.pg_pool:
        await app.state.pg_pool.close()
        logger.info("🔒 Database connection pool closed")


app = FastAPI(title="Harvis AI API", lifespan=lifespan)

db_pool = None
chat_history_manager = None

@app.on_event("shutdown")
async def shutdown_event():
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("Database pool closed")

""" 
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create connection pool
    try:
        # Fix database hostname: use pgsql-db instead of pgsql
        database_url = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")
        app.state.pg_pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=1, 
            max_size=10,
            command_timeout=30,  # Increased from 5 to 30 seconds
        )
        logger.info("✅ Database connection pool created")
        
        # Initialize session database
        from vibecoding.db_session import init_session_db
        await init_session_db(app.state.pg_pool)
        
        # Initialize chat history manager
        global chat_history_manager
        chat_history_manager = ChatHistoryManager(app.state.pg_pool)
        logger.info("✅ ChatHistoryManager initialized in lifespan")
        
        # Initialize vibe files database table
        try:
            from vibecoding.files import ensure_vibe_files_table
            await ensure_vibe_files_table()
            logger.info("✅ Vibe files database table initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize vibe files table: {e}")
        
    except Exception as e:
        logger.error(f"❌ Failed to create database pool: {e}")
        # Continue without pool - will fall back to direct connections
        app.state.pg_pool = None
    
    yield
    
    # Shutdown: close connection pool
    if hasattr(app.state, 'pg_pool') and app.state.pg_pool:
        await app.state.pg_pool.close()
        logger.info("🔒 Database connection pool closed")

# ─── FastAPI init --------------------------------------------------------------
app = FastAPI(title="Harvis AI API", lifespan=lifespan)

db_pool = None 
chat_history_manager = None  """

# CORS Middleware must be added before routes
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:9000",   # Main nginx proxy access point
        "http://127.0.0.1:9000",   # Main nginx proxy access point
        "http://localhost:3000",
        "http://localhost:3001", 
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://frontend:3000",    # Docker network
        "http://nginx-proxy:80",   # Docker network nginx
        "http://localhost:8000",   # Backend self
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    logger.info("Frontend directory mounted at %s", FRONTEND_DIR)

# Include vibecoding routers
app.include_router(sessions_router)
app.include_router(models_router)
app.include_router(execution_router)
app.include_router(files_router)
app.include_router(commands_router)
app.include_router(containers_router)

# ─── Device & models -----------------------------------------------------------
device = 0 if torch.cuda.is_available() else -1
logger.info("Using device: %s", "cuda" if device == 0 else "cpu")



# ─── Config --------------------------------------------------------------------
CLOUD_OLLAMA_URL = os.getenv("OLLAMA_CLOUD_URL", "https://coyotegpt.ngrok.app/ollama")
LOCAL_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
API_KEY = os.getenv("OLLAMA_API_KEY", "key")
DEFAULT_MODEL = "llama3.2:3b"

def make_ollama_request(endpoint, payload, timeout=90):
    """Make a POST request to Ollama with automatic fallback from cloud to local.
    Returns the response object from the successful request."""
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY != "key" else {}
    
    # Try cloud first
    try:
        logger.info("🌐 Trying cloud Ollama: %s", CLOUD_OLLAMA_URL)
        response = requests.post(f"{CLOUD_OLLAMA_URL}{endpoint}", json=payload, headers=headers, timeout=timeout)
        if response.status_code == 200:
            logger.info("✅ Cloud Ollama request successful")
            return response
        else:
            logger.warning("⚠️ Cloud Ollama returned status %s", response.status_code)
    except Exception as e:
        logger.warning("⚠️ Cloud Ollama request failed: %s", e)
    
    # Fallback to local
    try:
        logger.info("🏠 Falling back to local Ollama: %s", LOCAL_OLLAMA_URL)
        response = requests.post(f"{LOCAL_OLLAMA_URL}{endpoint}", json=payload, timeout=timeout)
        if response.status_code == 200:
            logger.info("✅ Local Ollama request successful")
            return response
        else:
            logger.error("❌ Local Ollama returned status %s", response.status_code)
            response.raise_for_status()
    except Exception as e:
        logger.error("❌ Local Ollama request failed: %s", e)
        raise
    
    return response

def make_ollama_get_request(endpoint, timeout=10):
    """Make a GET request to Ollama with automatic fallback from cloud to local.
    Returns the response object from the successful request."""
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY != "key" else {}
    
    # Try cloud first
    try:
        logger.info("🌐 Trying cloud Ollama GET: %s", CLOUD_OLLAMA_URL)
        response = requests.get(f"{CLOUD_OLLAMA_URL}{endpoint}", headers=headers, timeout=timeout)
        if response.status_code == 200:
            logger.info("✅ Cloud Ollama GET request successful")
            return response
        else:
            logger.warning("⚠️ Cloud Ollama GET returned status %s", response.status_code)
    except Exception as e:
        logger.warning("⚠️ Cloud Ollama GET request failed: %s", e)
    
    # Fallback to local
    try:
        logger.info("🏠 Falling back to local Ollama GET: %s", LOCAL_OLLAMA_URL)
        response = requests.get(f"{LOCAL_OLLAMA_URL}{endpoint}", timeout=timeout)
        if response.status_code == 200:
            logger.info("✅ Local Ollama GET request successful")
            return response
        else:
            logger.error("❌ Local Ollama GET returned status %s", response.status_code)
            response.raise_for_status()
    except Exception as e:
        logger.error("❌ Local Ollama GET request failed: %s", e)
        raise
    
    return response

def get_ollama_url():
    """Try cloud Ollama first, fallback to local if cloud fails.
    Returns the working Ollama URL for initialization purposes."""
    # Try cloud first
    try:
        headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY != "key" else {}
        response = requests.get(f"{CLOUD_OLLAMA_URL}/api/tags", headers=headers, timeout=5)
        if response.status_code == 200:
            logger.info("✅ Using cloud Ollama URL: %s", CLOUD_OLLAMA_URL)
            return CLOUD_OLLAMA_URL
    except Exception as e:
        logger.warning("⚠️ Cloud Ollama unavailable: %s", e)
    
    # Fallback to local
    try:
        response = requests.get(f"{LOCAL_OLLAMA_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            logger.info("✅ Using local Ollama URL: %s", LOCAL_OLLAMA_URL)
            return LOCAL_OLLAMA_URL
    except Exception as e:
        logger.error("❌ Local Ollama also unavailable: %s", e)
    
    # If both fail, default to cloud (let the actual request handle the error)
    logger.warning("⚠️ Both Ollama instances unavailable, defaulting to cloud")
    return CLOUD_OLLAMA_URL

# Get the working Ollama URL for initialization
OLLAMA_URL = get_ollama_url()

# ─── Pydantic schemas ----------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []
    model: str = DEFAULT_MODEL
    session_id: Optional[str] = None  # Chat session ID for history persistence
    audio_prompt: Optional[str] = None  # overrides HARVIS_VOICE_PATH if provided
    exaggeration: float = 0.5
    temperature: float = 0.8
    cfg_weight: float = 0.5

class ResearchChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []
    model: str = DEFAULT_MODEL
    session_id: Optional[str] = None  # Chat session ID for history persistence
    enableWebSearch: bool = True
    audio_prompt: Optional[str] = None  # overrides HARVIS_VOICE_PATH if provided
    exaggeration: float = 0.5
    temperature: float = 0.8
    cfg_weight: float = 0.5

class ScreenAnalysisRequest(BaseModel):
    image: str  # base-64 image (data-URI or raw)

class SynthesizeSpeechRequest(BaseModel):
    text: str
    audio_prompt: Optional[str] = None
    exaggeration: float = 0.5
    temperature: float = 0.8
    cfg_weight: float = 0.5

# VibeCommandRequest moved to vibecoding.commands

class AnalyzeAndRespondRequest(BaseModel):
    image: str  # base-64 image (data-URI or raw)
    model: str = DEFAULT_MODEL
    system_prompt: Optional[str] = None

class ScreenAnalysisWithTTSRequest(BaseModel):
    image: str  # base-64 image (data-URI or raw)
    model: str = DEFAULT_MODEL
    system_prompt: Optional[str] = None
    audio_prompt: Optional[str] = None
    exaggeration: float = 0.5
    temperature: float = 0.8
    cfg_weight: float = 0.5

# VibeCodingRequest moved to vibecoding.commands

class VoiceTranscribeRequest(BaseModel):
    model: str = DEFAULT_MODEL

class RunCommandRequest(BaseModel):
    command: str

class SaveFileRequest(BaseModel):
    filename: str
    content: str

# ─── Reasoning Model Helpers --------------------------------------------------
def separate_thinking_from_final_output(text: str) -> tuple[str, str]:
    """
    Extract the content between <think> and </think> tags and remove them from the text.
    Returns (reasoning/thoughts, final_answer)
    """
    thoughts = ""
    remaining_text = text
    
    # Extract all thinking blocks
    while "<think>" in remaining_text and "</think>" in remaining_text:
        start = remaining_text.find("<think>")
        end = remaining_text.find("</think>")
        
        if start != -1 and end != -1 and end > start:
            # Extract the content between tags (excluding the tags themselves)
            thought_content = remaining_text[start + len("<think>"):end].strip()
            if thought_content:
                thoughts += thought_content + "\n\n"
            
            # Remove the tags and their content from the original text
            remaining_text = remaining_text[:start] + remaining_text[end + len("</think>"):]
        else:
            break
    
    # Clean up the final answer
    final_answer = remaining_text.strip()
    reasoning = thoughts.strip()
    
    logger.info(f"Separated reasoning: {len(reasoning)} chars, final answer: {len(final_answer)} chars")
    
    return reasoning, final_answer

def has_reasoning_content(text: str) -> bool:
    """Check if text contains reasoning markers"""
    return "<think>" in text and "</think>" in text

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

# ─── Chat History Endpoints ───────────────────────────────────────────────────────
@app.post("/api/chat-history/sessions", response_model=ChatSession, tags=["chat-history"])
async def create_chat_session(
    request: CreateSessionRequest,
    current_user: Dict = Depends(get_current_user_optimized)
):
    """Create a new chat session"""
    try:
        session = await chat_history_manager.create_session(
            user_id=current_user['id'],
            title=request.title,
            model_used=request.model_used
        )
        return session
    except Exception as e:
        logger.error(f"Error creating chat session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create chat session")

@app.get("/api/chat-history/sessions", response_model=List[ChatSession], tags=["chat-history"])
async def get_user_chat_sessions(
    limit: int = 50,
    offset: int = 0,
    current_user: Dict = Depends(get_current_user_optimized)
):
    """Get all chat sessions for the current user"""
    try:
        sessions_response = await chat_history_manager.get_user_sessions(
            user_id=current_user['id'],
            limit=limit,
            offset=offset
        )
        return sessions_response.sessions
    except Exception as e:
        logger.error(f"Error getting user sessions: {e}")
        raise HTTPException(status_code=500, detail="Failed to get chat sessions")

@app.get("/api/chat-history/sessions/{session_id}", response_model=MessageHistoryResponse, tags=["chat-history"])
async def get_session_messages(
    session_id: str,
    limit: int = 100,
    offset: int = 0,
    current_user: UserResponse = Depends(get_current_user)
):
    """Get messages for a specific chat session"""
    try:
        # Convert string session_id to UUID
        session_uuid = UUID(session_id)
        logger.info(f"Getting messages for session {session_uuid}, user {current_user.id}")
        response = await chat_history_manager.get_session_messages(
            session_id=session_uuid,
            user_id=current_user.id,
            limit=limit,
            offset=offset
        )
        logger.info(f"Retrieved {len(response.messages)} messages for session {session_uuid}")
        
        # Return 404 if session doesn't exist
        if response.session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to get session messages")

class UpdateTitleRequest(BaseModel):
    title: str

@app.put("/api/chat-history/sessions/{session_id}/title", tags=["chat-history"])
async def update_session_title(
    session_id: str,
    request: UpdateTitleRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """Update chat session title"""
    try:
        # Convert string session_id to UUID
        session_uuid = UUID(session_id)
        success = await chat_history_manager.update_session_title(
            session_id=session_uuid,
            user_id=current_user.id,
            title=request.title
        )
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"success": True, "message": "Session title updated"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating session title: {e}")
        raise HTTPException(status_code=500, detail="Failed to update session title")

@app.delete("/api/chat-history/sessions/{session_id}", tags=["chat-history"])
async def delete_chat_session(
    session_id: str,
    current_user: UserResponse = Depends(get_current_user)
):
    """Delete a chat session"""
    try:
        # Convert string session_id to UUID
        session_uuid = UUID(session_id)
        success = await chat_history_manager.delete_session(
            session_id=session_uuid,
            user_id=current_user.id
        )
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"success": True, "message": "Session deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete session")

@app.delete("/api/chat-history/sessions/{session_id}/messages", tags=["chat-history"])
async def clear_session_messages(
    session_id: str,
    current_user: UserResponse = Depends(get_current_user)
):
    """Clear all messages from a chat session"""
    try:
        # Convert string session_id to UUID
        session_uuid = UUID(session_id)
        deleted_count = await chat_history_manager.clear_session_messages(
            session_id=session_uuid,
            user_id=current_user.id
        )
        return {"success": True, "message": f"Deleted {deleted_count} messages"}
    except Exception as e:
        logger.error(f"Error clearing session messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear session messages")

@app.get("/api/chat-history/search", response_model=List[ChatMessage], tags=["chat-history"])
async def search_messages(
    query: str,
    session_id: Optional[str] = None,
    limit: int = 50,
    current_user: UserResponse = Depends(get_current_user)
):
    """Search messages by content"""
    try:
        messages = await chat_history_manager.search_messages(
            user_id=current_user.id,
            query=query,
            session_id=session_id,
            limit=limit
        )
        return messages
    except Exception as e:
        logger.error(f"Error searching messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to search messages")

@app.get("/api/chat-history/stats", tags=["chat-history"])
async def get_user_chat_stats(
    current_user: UserResponse = Depends(get_current_user)
):
    """Get user chat statistics"""
    try:
        stats = await chat_history_manager.get_user_stats(current_user.id)
        return stats
    except Exception as e:
        logger.error(f"Error getting user stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user stats")

@app.post("/api/chat-history/messages", response_model=ChatMessage, tags=["chat-history"])
async def add_message_to_session(
    message_request: CreateMessageRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """Add a message to a chat session"""
    try:
        # Verify the user owns the session
        session = await chat_history_manager.get_session(message_request.session_id, current_user.id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Add the message using the new manager API
        added_message = await chat_history_manager.add_message(
            user_id=current_user.id,
            session_id=message_request.session_id,
            role=message_request.role,
            content=message_request.content,
            reasoning=message_request.reasoning,
            model_used=message_request.model_used,
            input_type=message_request.input_type,
            metadata=message_request.metadata
        )
        return added_message
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding message: {e}")
        raise HTTPException(status_code=500, detail="Failed to add message")

# ─── Authentication Endpoints ─────────────────────────────────────────────────────
@app.post("/api/auth/signup", response_model=TokenResponse, tags=["auth"])
async def signup(request: SignupRequest, app_request: Request):
    # Use connection pool if available
    pool = getattr(app_request.app.state, 'pg_pool', None)
    
    if pool:
        async with pool.acquire() as conn:
            return await _signup_with_connection(request, conn)
    else:
        conn = await asyncpg.connect(DATABASE_URL, timeout=10)
        try:
            return await _signup_with_connection(request, conn)
        finally:
            await conn.close()

async def _signup_with_connection(request: SignupRequest, conn):
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

@app.post("/api/auth/login", tags=["auth"])
async def login(request: AuthRequest, app_request: Request):
    # Use connection pool if available
    pool = getattr(app_request.app.state, 'pg_pool', None)
    
    if pool:
        async with pool.acquire() as conn:
            return await _login_with_connection(request, conn)
    else:
        conn = await asyncpg.connect(DATABASE_URL, timeout=10)
        try:
            return await _login_with_connection(request, conn)
        finally:
            await conn.close()

async def _login_with_connection(request: AuthRequest, conn):
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
        
        response = JSONResponse(content={"access_token": access_token, "token_type": "bearer"})
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            samesite="lax",
            secure=False,  # Set to True in production with HTTPS
        )
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/auth/me", response_model=UserResponse, tags=["auth"])
async def get_current_user_info(current_user: Dict = Depends(get_current_user_optimized)):
    """Optimized user info endpoint with caching"""
    return UserResponse(**current_user)

@app.get("/api/auth/stats", tags=["auth"])
async def get_authentication_stats():
    """Get authentication performance statistics"""
    return get_auth_stats()

# Import new modules




@app.post("/api/chat", tags=["chat"])
async def chat(req: ChatRequest, request: Request, current_user: Dict = Depends(get_current_user_optimized)):
    """
    Main conversational endpoint with persistent chat history.
    Produces: JSON {history, audio_path, session_id}
    """
    try:
        logger.info(f"Chat endpoint reached - User: {current_user['username']}, Message: {req.message[:50]}...")
        # ── 1. Handle chat session and history ──────────────────────────────────────────
        session_id = req.session_id
        
        # If no session provided, get recent messages from provided history or use empty history
        if session_id:
            try:
                # Convert session_id string to UUID
                from uuid import UUID
                session_uuid = UUID(session_id)
                
                # Get recent messages from database for context
                recent_messages = await chat_history_manager.get_recent_messages(
                    session_id=session_uuid, 
                    user_id=current_user['id'], 
                    limit=10
                )
            except (ValueError, Exception) as e:
                logger.error(f"Invalid session_id format or error loading context: {e}")
                # Fallback to request history if session_id is invalid
                recent_messages = []
            # Convert to format expected by model
            history = chat_history_manager.format_messages_for_context(recent_messages)
            logger.info(f"Using session {session_id} with {len(recent_messages)} recent messages")
        else:
            # Use provided history or empty
            history = req.history
            logger.info("No session provided, using request history")
        
        # Add current user message to history
        history = history + [{"role": "user", "content": req.message}]
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
            # Load system prompt from file
            system_prompt_path = os.path.join(os.path.dirname(__file__), "system_prompt.txt")
            try:
                with open(system_prompt_path, 'r', encoding='utf-8') as f:
                    system_prompt = f.read().strip()
            except FileNotFoundError:
                logger.warning("system_prompt.txt not found, using default prompt")
                system_prompt = (
                    'You are "Jarves", a voice-first local assistant. '
                    "Reply in ≤25 spoken-style words, sprinkling brief Spanish when natural, Be bilangual about 80 percent english and 20 percent spanish"
                    'Begin each answer with a short verbal acknowledgment (e.g., "Claro,", "¡Por supuesto!", "Right away").'
                )
            OLLAMA_ENDPOINT = "/api/chat"  # single source of truth

            # Build messages array with conversation history
            messages = [{"role": "system", "content": system_prompt}]
            
            # Add conversation history (excluding the current message that will be added)
            for msg in history[:-1]:  # Exclude the last message which is the current user message
                messages.append({"role": msg["role"], "content": msg["content"]})
            
            # Add current user message
            messages.append({"role": "user", "content": req.message})
            
            payload = {
                "model": req.model,
                "messages": messages,
                "stream": False,
            }
            
            logger.info(f"💬 CHAT: Sending {len(messages)} messages to Ollama (including {len(history)-1} context messages)")

            logger.info("💬 CHAT: Using model '%s' for Ollama %s", req.model, OLLAMA_ENDPOINT)

            resp = make_ollama_request(OLLAMA_ENDPOINT, payload, timeout=90)

            if resp.status_code != 200:
                logger.error("Ollama error %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()

            response_text = resp.json().get("message", {}).get("content", "").strip()

        # ── 4. Process reasoning content if present
        reasoning_content = ""
        final_answer = response_text
        
        if has_reasoning_content(response_text):
            reasoning_content, final_answer = separate_thinking_from_final_output(response_text)
            logger.info(f"🧠 Reasoning model detected - separated thinking from final answer")
        
        # ── 5. Persist chat history to database ─────────────────────────────────────────
        if session_id:
            try:
                # Create session if it doesn't exist
                session = await chat_history_manager.get_session(session_id, current_user.id)
                if not session:
                    session = await chat_history_manager.create_session(
                        user_id=current_user.id,
                        title="New Chat",
                        model_used=req.model
                    )
                    session_id = session.id
                
                # Save user message
                await chat_history_manager.add_message(
                    user_id=current_user.id,
                    session_id=session_id,
                    role="user",
                    content=req.message,
                    model_used=req.model,
                    input_type="text"
                )
                
                # Save assistant message
                await chat_history_manager.add_message(
                    user_id=current_user.id,
                    session_id=session_id,
                    role="assistant",
                    content=final_answer,
                    reasoning=reasoning_content if reasoning_content else None,
                    model_used=req.model,
                    input_type="text"
                )
                
                logger.info(f"💾 Saved chat messages to session {session_id}")
                
            except Exception as e:
                logger.error(f"Error saving chat history: {e}")
                # Don't fail the entire request if history saving fails
        else:
            # Create new session for this conversation if none provided
            try:
                session = await chat_history_manager.create_session(
                    user_id=current_user.id,
                    title="New Chat",
                    model_used=req.model
                )
                session_id = session.id
                
                # Save messages to new session
                await chat_history_manager.add_message(
                    user_id=current_user.id,
                    session_id=session_id,
                    role="user",
                    content=req.message,
                    model_used=req.model,
                    input_type="text"
                )
                
                await chat_history_manager.add_message(
                    user_id=current_user.id,
                    session_id=session_id,
                    role="assistant",
                    content=final_answer,
                    reasoning=reasoning_content if reasoning_content else None,
                    model_used=req.model,
                    input_type="text"
                )
                
                logger.info(f"💾 Created new session {session_id} and saved messages")
                
            except Exception as e:
                logger.error(f"Error creating session and saving history: {e}")
                session_id = None  # Set to None if creation fails
        
        # ── 6. Update history with assistant reply (use final answer only for chat history)
        new_history = history + [{"role": "assistant", "content": final_answer}]

        # ── 7. Text-to-speech -----------------------------------------------------------
        # Handle audio prompt path
        audio_prompt_path = req.audio_prompt or HARVIS_VOICE_PATH
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

        # Use VRAM-optimized TTS generation with only final_answer (not the reasoning process)
        sr, wav = generate_speech_optimized(
            text=final_answer,
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

        response_data = {
            "history": new_history,
            "audio_path": f"/api/audio/{filename}",  # FastAPI route below (or nginx alias /audio/)
            "session_id": session_id  # Include session ID for frontend
        }
        
        # Add reasoning content if present
        if reasoning_content:
            response_data["reasoning"] = reasoning_content
            response_data["final_answer"] = final_answer
            logger.info(f"🧠 Returning reasoning content ({len(reasoning_content)} chars)")
        
        return response_data

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
        # Unload ALL models to free maximum GPU memory for Qwen2VL
        logger.info("🖼️ Starting screen analysis - clearing ALL GPU memory")
        unload_all_models()  # Unload everything for maximum memory
        
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

        # Unload Qwen2VL immediately after use to free memory
        logger.info("🔄 Unloading Qwen2VL after screen analysis")
        unload_qwen_model()
        
        # Use LLM to get a response based on the caption
        llm_system_prompt = "You are an AI assistant that helps users understand what's on their screen. Provide a concise and helpful response based on the screen content."
        llm_user_prompt = f"Here's what's on the user's screen: {qwen_caption}\nWhat should they do next?"
        llm_response = query_llm(llm_user_prompt, system_prompt=llm_system_prompt)
        
        # Reload TTS/Whisper models for future use
        logger.info("🔄 Reloading TTS/Whisper models after screen analysis")
        reload_models_if_needed()
        
        logger.info("✅ Screen analysis complete - all models restored")
        return {"commentary": qwen_caption, "llm_response": llm_response}

    except Exception as e:
        logger.error("Screen analysis failed: %s", e)
        # Ensure models are reloaded even on error
        logger.info("🔄 Reloading models after error")
        reload_models_if_needed()
        raise HTTPException(500, str(e)) from e

# Global rate limiting and circuit breaker for vision endpoints
import asyncio
_vision_processing_lock = asyncio.Lock()
_last_vision_request_time = 0
_vision_endpoint_enabled = True  # Emergency disable flag
_vision_request_count = 0
_vision_error_count = 0

@app.post("/api/analyze-and-respond", tags=["vision"])
async def analyze_and_respond(req: AnalyzeAndRespondRequest):
    """
    Analyze screen with Qwen vision model and get LLM response using selected model.
    Features intelligent model management to optimize GPU memory usage.
    """
    global _last_vision_request_time, _vision_endpoint_enabled, _vision_request_count, _vision_error_count
    
    # Circuit breaker: Check if endpoint is disabled
    if not _vision_endpoint_enabled:
        logger.warning("🚫 Vision endpoint is disabled due to repeated issues")
        raise HTTPException(status_code=503, detail="Vision analysis temporarily disabled")
    
    # Circuit breaker: Check error rate
    if _vision_request_count > 10 and _vision_error_count / _vision_request_count > 0.8:
        logger.error("🚫 Circuit breaker activated: too many failures")
        _vision_endpoint_enabled = False
        raise HTTPException(status_code=503, detail="Vision analysis disabled due to high error rate")
    
    _vision_request_count += 1
    logger.info(f"📊 Vision request #{_vision_request_count} (errors: {_vision_error_count})")
    
    # Rate limiting: only allow one vision request at a time
    async with _vision_processing_lock:
        current_time = time.time()
        
        # Enforce minimum 2 second delay between requests
        time_since_last = current_time - _last_vision_request_time
        if time_since_last < 2.0:
            wait_time = 2.0 - time_since_last
            logger.info(f"⏳ Rate limiting: waiting {wait_time:.1f}s before processing vision request")
            await asyncio.sleep(wait_time)
        
        _last_vision_request_time = time.time()
        
        temp_image_path = None
        try:
            # Unload ALL models to free maximum GPU memory for Qwen2VL
            logger.info("🖼️ Starting enhanced screen analysis - clearing ALL GPU memory")
            unload_all_models()  # Unload everything for maximum memory
            
            # Add explicit garbage collection and memory cleanup
            import gc
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
            
            # Decode base64 image and save to a temporary file
            try:
                image_data = base64.b64decode(req.image.split(",")[1])
            except (IndexError, ValueError) as e:
                logger.error(f"Invalid image data format: {e}")
                raise HTTPException(status_code=400, detail="Invalid image data format")
                
            temp_image_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.png")
            with open(temp_image_path, "wb") as f:
                f.write(image_data)

            # Use Qwen to analyze the image
            qwen_prompt = "Analyze this screen in detail. Describe what you see, including any text, UI elements, applications, and content visible."
            logger.info("🔍 Analyzing screen with Qwen2VL...")
            
            try:
                qwen_analysis = query_qwen(temp_image_path, qwen_prompt)
            except Exception as e:
                logger.error(f"Qwen2VL analysis failed: {e}")
                raise HTTPException(status_code=500, detail=f"Screen analysis failed: {str(e)}")
            finally:
                # Always clean up temp file, even if analysis fails
                if temp_image_path and os.path.exists(temp_image_path):
                    try:
                        os.remove(temp_image_path)
                        temp_image_path = None
                    except OSError as e:
                        logger.warning(f"Failed to remove temp file {temp_image_path}: {e}")

            if "[Qwen error]" in qwen_analysis:
                raise HTTPException(status_code=500, detail=qwen_analysis)

            # Unload Qwen2VL immediately after analysis to free memory for LLM
            logger.info("🔄 Unloading Qwen2VL after analysis, preparing for LLM")
            unload_qwen_model()
            
            # Additional cleanup after Qwen unload
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            # Use the selected LLM model to generate a response based on Qwen's analysis
            # Use custom system prompt if provided, otherwise use default
            system_prompt = req.system_prompt or "You are Harvis AI, an AI assistant analyzing what the user is seeing on their screen. Provide helpful insights, suggestions, or commentary about what you observe. Be conversational and helpful."
            
            logger.info(f"🤖 Generating response with {req.model}")
            if req.model == "gemini-1.5-flash":
                # Use Gemini for response
                try:
                    llm_response = query_gemini(f"Screen analysis: {qwen_analysis}\n\nPlease provide helpful insights about this screen.", [])
                except Exception as e:
                    logger.error(f"Gemini response failed: {e}")
                    raise HTTPException(status_code=500, detail=f"AI response generation failed: {str(e)}")
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
                headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY != "key" else {}
                
                try:
                    resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, headers=headers, timeout=90)
                    
                    if resp.status_code != 200:
                        logger.error("Ollama error %s: %s", resp.status_code, resp.text)
                        raise HTTPException(status_code=500, detail=f"LLM request failed with status {resp.status_code}")
                    
                    llm_response = resp.json().get("message", {}).get("content", "").strip()
                    
                    if not llm_response:
                        logger.warning("Empty response from Ollama")
                        llm_response = "I was able to analyze the screen but couldn't generate a detailed response. Please try again."
                        
                except requests.RequestException as e:
                    logger.error(f"Ollama request failed: {e}")
                    raise HTTPException(status_code=500, detail=f"AI service unavailable: {str(e)}")

            # Reload TTS/Whisper models for future use
            logger.info("🔄 Reloading TTS/Whisper models after enhanced screen analysis")
            reload_models_if_needed()

            logger.info("✅ Enhanced screen analysis complete - all models restored")
            return {
                "response": llm_response,
                "screen_analysis": qwen_analysis,
                "model_used": req.model
            }

        except HTTPException:
            # Re-raise HTTP exceptions without wrapping
            _vision_error_count += 1
            raise
        except Exception as e:
            _vision_error_count += 1
            logger.error(f"Analyze and respond failed with unexpected error: {e}", exc_info=True)
            raise HTTPException(500, f"Internal server error: {str(e)}") from e
        finally:
            # Cleanup: Always ensure temp file is removed and models are restored
            if temp_image_path and os.path.exists(temp_image_path):
                try:
                    os.remove(temp_image_path)
                except OSError as e:
                    logger.warning(f"Failed to remove temp file in finally block: {e}")
            
            # Ensure models are reloaded even on error
            try:
                logger.info("🔄 Ensuring models are reloaded after request completion")
                reload_models_if_needed()
            except Exception as e:
                logger.error(f"Failed to reload models in finally block: {e}")
                
            # Final memory cleanup
            import gc
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

@app.post("/api/vision-control", tags=["vision"])
async def vision_control(action: str = "status"):
    """
    Emergency control endpoint for vision processing
    Actions: 'disable', 'enable', 'status', 'reset'
    """
    global _vision_endpoint_enabled, _vision_request_count, _vision_error_count
    
    if action == "disable":
        _vision_endpoint_enabled = False
        logger.warning("🚫 Vision endpoint manually disabled")
        return {"status": "disabled", "message": "Vision analysis disabled"}
    
    elif action == "enable":
        _vision_endpoint_enabled = True
        logger.info("✅ Vision endpoint manually enabled")
        return {"status": "enabled", "message": "Vision analysis enabled"}
    
    elif action == "reset":
        _vision_endpoint_enabled = True
        _vision_request_count = 0
        _vision_error_count = 0
        logger.info("🔄 Vision endpoint stats reset")
        return {"status": "reset", "message": "Vision stats reset"}
    
    else:  # status
        return {
            "enabled": _vision_endpoint_enabled,
            "total_requests": _vision_request_count,
            "total_errors": _vision_error_count,
            "error_rate": _vision_error_count / max(_vision_request_count, 1),
            "status": "enabled" if _vision_endpoint_enabled else "disabled"
        }

@app.post("/api/analyze-screen-with-tts", tags=["vision"])
async def analyze_screen_with_tts(req: ScreenAnalysisWithTTSRequest):
    """
    Complete screen analysis with Qwen2VL + LLM response + TTS audio output.
    Implements intelligent model management: Qwen2VL -> LLM -> TTS pipeline.
    """
    try:
        # Phase 1: Unload ALL models for maximum memory for Qwen2VL processing
        logger.info("🖼️ Phase 1: Starting screen analysis - clearing ALL GPU memory for Qwen2VL")
        unload_all_models()
        
        # Decode base64 image and save to a temporary file
        image_data = base64.b64decode(req.image.split(",")[1])
        temp_image_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.png")
        with open(temp_image_path, "wb") as f:
            f.write(image_data)

        # Use Qwen2VL to analyze the image
        qwen_prompt = "Analyze this screen comprehensively. Describe what you see, including any text, UI elements, applications, and content. Focus on what the user might need help with."
        logger.info("🔍 Analyzing screen with Qwen2VL...")
        qwen_analysis = query_qwen(temp_image_path, qwen_prompt)
        os.remove(temp_image_path)

        if "[Qwen error]" in qwen_analysis:
            raise HTTPException(status_code=500, detail=qwen_analysis)

        # Phase 2: Unload Qwen2VL to free memory for LLM processing
        logger.info("🤖 Phase 2: Unloading Qwen2VL, generating LLM response")
        unload_qwen_model()
        
        # Generate LLM response
        system_prompt = req.system_prompt or "You are Harvis AI, an AI assistant. Based on the screen analysis, provide helpful, conversational insights. Keep responses under 100 words for voice output."
        
        if req.model == "gemini-1.5-flash":
            llm_response = query_gemini(f"Screen analysis: {qwen_analysis}\n\nProvide helpful insights about this screen.", [])
        else:
            payload = {
                "model": req.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Screen analysis: {qwen_analysis}\n\nProvide helpful insights about this screen."},
                ],
                "stream": False,
            }
            headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY != "key" else {}
            resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, headers=headers, timeout=90)
            resp.raise_for_status()
            llm_response = resp.json().get("message", {}).get("content", "").strip()

        # Phase 3: Reload TTS for audio generation
        logger.info("🔊 Phase 3: Reloading TTS for audio generation")
        reload_models_if_needed()
        
        # Generate TTS audio
        audio_prompt_path = req.audio_prompt or HARVIS_VOICE_PATH
        if not os.path.isfile(audio_prompt_path):
            logger.warning(f"Audio prompt {audio_prompt_path} not found, using default voice")
            audio_prompt_path = None

        sr, wav = generate_speech_optimized(
            text=llm_response,
            audio_prompt=audio_prompt_path,
            exaggeration=req.exaggeration,
            temperature=req.temperature,
            cfg_weight=req.cfg_weight,
        )

        # Save audio file
        filename = f"screen_analysis_{uuid.uuid4()}.wav"
        filepath = os.path.join(tempfile.gettempdir(), filename)
        sf.write(filepath, wav, sr)
        
        logger.info("✅ Complete screen analysis with TTS finished")
        return {
            "response": llm_response,
            "screen_analysis": qwen_analysis,
            "model_used": req.model,
            "audio_path": f"/api/audio/{filename}",
            "processing_stages": {
                "qwen_analysis": "✅ Completed",
                "llm_response": "✅ Completed", 
                "tts_generation": "✅ Completed"
            }
        }

    except Exception as e:
        logger.error("Screen analysis with TTS failed: %s", e)
        # Ensure models are reloaded on error
        reload_models_if_needed()
        raise HTTPException(500, str(e)) from e

# Whisper model will be loaded on demand

@app.post("/api/mic-chat", tags=["voice"])
async def mic_chat(file: UploadFile = File(...), model: str = Form(DEFAULT_MODEL), session_id: Optional[str] = Form(None), current_user: Dict = Depends(get_current_user_optimized)):
    try:
        # DEBUG: Log the received model parameter
        logger.info(f"🎤 MIC-CHAT: Received model parameter: '{model}' (type: {type(model)})")
        logger.info(f"🎤 MIC-CHAT: DEFAULT_MODEL is: '{DEFAULT_MODEL}'")
        
        # Save uploaded file to temp
        contents = await file.read()
        logger.info(f"Received audio data: {len(contents)} bytes, content_type: {file.content_type}")
        
        if len(contents) == 0:
            raise HTTPException(400, "No audio data received")
        
        # Detect actual audio format from header
        header = contents[:4]
        logger.info(f"Audio file header: {header}")
        
        # Use appropriate file extension based on actual format
        if header == b'RIFF':
            file_ext = ".wav"
        elif header == b'OggS':
            file_ext = ".ogg"
        elif header.startswith(b'ID3') or header.startswith(b'\xff\xfb'):
            file_ext = ".mp3"
        elif header.startswith(b'\x1a\x45\xdf\xa3'):  # WebM/Matroska
            file_ext = ".webm"
        else:
            logger.warning(f"Unknown audio format, header: {header}, trying as original filename")
            # Use original filename extension if available
            if hasattr(file, 'filename') and file.filename:
                _, file_ext = os.path.splitext(file.filename)
                if not file_ext:
                    file_ext = ".wav"
            else:
                file_ext = ".wav"
            
        tmp_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}{file_ext}")
        with open(tmp_path, "wb") as f:
            f.write(contents)
        
        logger.info(f"Saved audio file as: {tmp_path}")

        # Use VRAM-optimized transcription (automatically handles model loading/unloading)
        try:
            result = transcribe_with_whisper_optimized(tmp_path)
        except Exception as e:
            logger.error(f"VRAM-optimized transcription failed: {e}")
            raise HTTPException(500, f"Transcription failed: {str(e)}")
            
        logger.info(f"Whisper transcription result: {result}")
        
        message = result.get("text", "").strip()
        logger.info(f"MIC input transcribed: {message}")

        if not message:
            raise HTTPException(400, "Could not transcribe anything.")
        
        # Check for Whisper hallucinations (common phrases with high no_speech_prob)
        segments = result.get("segments", [])
        if segments:
            avg_no_speech_prob = sum(seg.get("no_speech_prob", 0) for seg in segments) / len(segments)
            logger.info(f"Average no_speech_prob: {avg_no_speech_prob}")
            
            # Common Whisper hallucinations
            hallucination_phrases = [
                "thanks for watching", "thank you for watching", "thanks for listening",
                "subscribe", "like and subscribe", "don't forget to subscribe",
                "see you next time", "bye", "goodbye", "hello", "hi there",
                "welcome back", "welcome to", "this is"
            ]
            
            message_lower = message.lower().strip(".,!?")
            if (avg_no_speech_prob > 0.6 and 
                any(phrase in message_lower for phrase in hallucination_phrases)):
                logger.warning(f"Likely hallucination detected: '{message}' (no_speech_prob: {avg_no_speech_prob})")
                raise HTTPException(400, "Audio unclear - Whisper detected mostly silence. Please speak louder and closer to microphone.")

        # Clean up temp files
        try:
            os.unlink(tmp_path)
        except:
            pass

        # Now use existing chat logic with the selected model
        logger.info(f"🎤 MIC-CHAT: Creating ChatRequest with model: '{model}' and session_id: '{session_id}'")
        chat_req = ChatRequest(message=message, model=model, session_id=session_id)
        return await chat(chat_req, request=None, current_user=current_user)

    except Exception as e:
        logger.exception("Mic chat failed")
        # Clean up temp files on error
        try:
            if 'tmp_path' in locals():
                os.unlink(tmp_path)
                # Also clean up amplified file if it exists
                if tmp_path.endswith('_amplified.wav'):
                    original_path = tmp_path.replace('_amplified.wav', '.ogg')
                    try:
                        os.unlink(original_path)
                    except:
                        pass
        except:
            pass
        raise HTTPException(500, str(e))

# Research endpoints using the enhanced research module with advanced pipeline
from agent_research import research_agent, fact_check_agent, comparative_research_agent
from agent_research import async_research_agent, async_fact_check_agent, async_comparative_research_agent
from agent_research import get_research_agent_stats, get_mcp_tool
from research.web_search import WebSearchAgent
from pydantic import Field
from typing import Optional, List

class AdvancedResearchRequest(BaseModel):
    """Enhanced research request with advanced options"""
    message: str
    model: str = "mistral"
    history: List[Dict[str, str]] = []
    use_advanced: bool = Field(default=False, description="Use advanced research pipeline")
    enable_streaming: bool = Field(default=False, description="Enable streaming progress")
    enable_verification: bool = Field(default=True, description="Enable response verification")

@app.post("/api/research-chat", tags=["research"])
async def research_chat(req: Union[ResearchChatRequest, AdvancedResearchRequest]):
    """
    Enhanced research chat endpoint with advanced pipeline support
    """
    try:
        if not req.message:
            return {"error": "Message is required"}, 400

        # Check if using advanced features
        use_advanced = getattr(req, 'use_advanced', False)
        enable_streaming = getattr(req, 'enable_streaming', False)
        enable_verification = getattr(req, 'enable_verification', True)

        # Unload models to free GPU memory for research processing
        logger.info(f"🔍 Starting research (advanced: {use_advanced}) - unloading models to free GPU memory")
        unload_models()

        # Call the appropriate research agent
        if use_advanced:
            # Use advanced async research agent
            response_data = await async_research_agent(
                query=req.message, 
                model=req.model,
                enable_streaming=enable_streaming
            )
            
            # Handle streaming response
            if enable_streaming and hasattr(response_data, '__aiter__'):
                # For streaming, we need to collect the final result
                final_response = ""
                async for chunk in response_data:
                    final_response += chunk
                response_content = final_response
            else:
                response_content = response_data
                
            # Format advanced response
            if isinstance(response_content, str) and not response_content.startswith("Research failed"):
                sources = []  # Sources are embedded in advanced response
                sources_found = "embedded"
            else:
                response_content = f"Advanced Research Error: {response_content}"
                sources = []
                sources_found = 0
        else:
            # Use backward compatible research agent
            response_data = research_agent(req.message, req.model, use_advanced=False)
            
            # Format response for chat interface
            if "error" in response_data:
                response_content = f"Research Error: {response_data['error']}"
                sources = []
                sources_found = 0
            else:
                # Format the comprehensive research response
                analysis = response_data.get("analysis", "No analysis available")
                sources = response_data.get("sources", [])
                sources_found = response_data.get("sources_found", 0)
                
                response_content = f"{analysis}\n\n"
                
                if sources:
                    response_content += f"**Sources ({sources_found} found):**\n"
                    logger.info(f"Formatting {len(sources)} sources for display")
                    for i, source in enumerate(sources[:5], 1):  # Limit to top 5 sources
                        title = source.get('title', 'Unknown Title')
                        url = source.get('url', 'No URL')
                        logger.info(f"Source {i}: title='{title}', url='{url}'")
                        response_content += f"{i}. [{title}]({url})\n"

        # ── Process reasoning content if present in research response
        research_reasoning = ""
        final_research_answer = response_content
        
        if has_reasoning_content(response_content):
            research_reasoning, final_research_answer = separate_thinking_from_final_output(response_content)
            logger.info(f"🧠 Research reasoning model detected - separated thinking from final answer")
        
        # Update history with assistant reply (use final answer only for chat history)
        new_history = req.history + [{"role": "assistant", "content": final_research_answer}]

        # ── Generate TTS for research response ──────────────────────────────────────────
        logger.info("🔊 Research complete - preparing TTS generation")

        # Handle audio prompt path
        audio_prompt_path = req.audio_prompt or HARVIS_VOICE_PATH
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

        # Create a more conversational version of the research response for TTS
        # Use final_research_answer (without reasoning) for TTS
        # Remove markdown formatting and make it more speech-friendly
        tts_text = final_research_answer.replace("**", "").replace("*", "").replace("#", "")
        # Replace numbered lists with more natural speech
        import re
        tts_text = re.sub(r'^\d+\.\s*', '', tts_text, flags=re.MULTILINE)
        # Replace markdown links with just the title
        tts_text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', tts_text)
        # Limit length for TTS (keep it conversational)
        if len(tts_text) > 800:
            tts_text = tts_text[:800] + "... and more details are available in the sources."

        sr, wav = generate_speech_optimized(
            text=tts_text,
            audio_prompt=audio_prompt_path,
            exaggeration=req.exaggeration,
            temperature=req.temperature,
            cfg_weight=req.cfg_weight,
        )

        # ── Persist WAV to /tmp so it can be served ──────────────────────────────────────
        filename = f"research_{uuid.uuid4()}.wav"
        filepath = os.path.join(tempfile.gettempdir(), filename)
        sf.write(filepath, wav, sr)
        logger.info("Research TTS audio written to %s", filepath)

        research_response_data = {
            "history": new_history, 
            "response": final_research_answer,  # Use final answer for response
            "audio_path": f"/api/audio/{filename}"
        }
        
        # Add reasoning content if present
        if research_reasoning:
            research_response_data["reasoning"] = research_reasoning
            research_response_data["final_answer"] = final_research_answer
            logger.info(f"🧠 Returning research reasoning content ({len(research_reasoning)} chars)")
        
        return research_response_data

    except Exception as e:
        logger.exception("Research chat endpoint crashed")
        raise HTTPException(500, str(e))

class FactCheckRequest(BaseModel):
    claim: str
    model: str = DEFAULT_MODEL

class ComparativeResearchRequest(BaseModel):
    topics: List[str]
    model: str = DEFAULT_MODEL

class WebSearchRequest(BaseModel):
    query: str
    max_results: int = 5
    extract_content: bool = False

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

@app.post("/api/web-search", tags=["research"])
async def web_search(req: WebSearchRequest):
    """
    Perform web search using LangChain search agents
    """
    try:
        logger.info(f"Web search request: query='{req.query}', max_results={req.max_results}, extract_content={req.extract_content}")
        
        # Initialize the web search agent
        search_agent = WebSearchAgent(max_results=req.max_results)
        
        if req.extract_content:
            # Search and extract content from URLs
            logger.info("Performing search with content extraction...")
            result = search_agent.search_and_extract(req.query, extract_content=True)
        else:
            # Just search without content extraction
            logger.info("Performing basic search...")
            search_results = search_agent.search_web(req.query, req.max_results)
            result = {
                "query": req.query,
                "search_results": search_results,
                "extracted_content": []
            }
        
        logger.info(f"Search completed: found {len(result.get('search_results', []))} results")
        return result
    except Exception as e:
        logger.exception(f"Web search endpoint crashed for query '{req.query}': {str(e)}")
        raise HTTPException(500, f"Search failed: {str(e)}")

# ─── Warmup ────────────────────────────────────────────────────────
# Models will be loaded on demand to manage GPU memory efficiently
logger.info("Models will be loaded on demand for optimal memory management")

# ─── Dev entry-point -----------------------------------------------------------
@app.get("/api/ollama-models", tags=["models"])
async def get_ollama_models():
    """
    Fetches the list of available models from the Ollama server.
    """
    try:
        url = f"{OLLAMA_URL}/api/tags"
        headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY != "key" else {}
        logger.info(f"Trying to connect to Ollama at: {url}")
        logger.info(f"Using headers: {headers}")
        response = requests.get(url, headers=headers, timeout=10)
        logger.info(f"Ollama response status: {response.status_code}")
        logger.info(f"Ollama response headers: {response.headers}")
        logger.info(f"Ollama response text (first 200 chars): {response.text[:200]}")
        
        response.raise_for_status()
        models = response.json().get("models", [])
        ollama_model_names = [model["name"] for model in models]
        logger.info(f"Available models from Ollama server: {ollama_model_names}")

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
    except ValueError as e:
        logger.error(f"JSON parsing error from Ollama: {e}")
        logger.error(f"Response content: {response.text}")
        raise HTTPException(
            status_code=503, detail="Invalid response from Ollama server"
        )

# Vibe command endpoint moved to vibecoding.commands

# Vibe websocket endpoint moved to vibecoding.commands

# ─── User Ollama Settings ──────────────────────────────────────────────────────
class OllamaSettings(BaseModel):
    cloud_url: str
    local_url: str
    api_key: str
    preferred_endpoint: str  # "cloud", "local", or "auto"

# Global settings dict (in production, this would be stored in database per user)
user_ollama_settings = {}

@app.get("/api/user/ollama-settings", tags=["settings"])
async def get_ollama_settings(current_user: dict = Depends(get_current_user_optimized)):
    """Get current user's Ollama settings"""
    user_id = current_user.get("id")
    default_settings = {
        "cloud_url": CLOUD_OLLAMA_URL,
        "local_url": LOCAL_OLLAMA_URL,
        "api_key": "****" if API_KEY != "key" else "",
        "preferred_endpoint": "auto"
    }
    
    user_settings = user_ollama_settings.get(str(user_id), default_settings)
    logger.info(f"Retrieved Ollama settings for user {user_id}: {user_settings}")
    return user_settings

@app.post("/api/user/ollama-settings", tags=["settings"])
async def update_ollama_settings(
    settings: OllamaSettings,
    current_user: dict = Depends(get_current_user_optimized)
):
    """Update current user's Ollama settings"""
    user_id = current_user.get("id")
    
    # Store settings for user (in production, save to database)
    user_ollama_settings[str(user_id)] = {
        "cloud_url": settings.cloud_url,
        "local_url": settings.local_url,
        "api_key": settings.api_key,
        "preferred_endpoint": settings.preferred_endpoint
    }
    
    logger.info(f"Updated Ollama settings for user {user_id}: {settings.dict()}")
    return {"message": "Ollama settings updated successfully", "settings": settings.dict()}

@app.post("/api/user/ollama-test-connection", tags=["settings"])
async def test_ollama_connection(
    settings: OllamaSettings,
    current_user: dict = Depends(get_current_user_optimized)
):
    """Test connection to Ollama with provided settings"""
    user_id = current_user.get("id")
    results = {"cloud": None, "local": None}
    
    # Test cloud connection
    if settings.cloud_url and settings.cloud_url.strip():
        try:
            headers = {"Authorization": f"Bearer {settings.api_key}"} if settings.api_key and settings.api_key != "key" else {}
            response = requests.get(f"{settings.cloud_url}/api/tags", headers=headers, timeout=10)
            if response.status_code == 200:
                models = response.json().get("models", [])
                results["cloud"] = {
                    "status": "success",
                    "model_count": len(models),
                    "models": [m.get("name", "unknown") for m in models[:5]]  # First 5 models
                }
            else:
                results["cloud"] = {"status": "error", "message": f"HTTP {response.status_code}"}
        except Exception as e:
            results["cloud"] = {"status": "error", "message": str(e)}
    
    # Test local connection
    if settings.local_url and settings.local_url.strip():
        try:
            response = requests.get(f"{settings.local_url}/api/tags", timeout=10)
            if response.status_code == 200:
                models = response.json().get("models", [])
                results["local"] = {
                    "status": "success", 
                    "model_count": len(models),
                    "models": [m.get("name", "unknown") for m in models[:5]]  # First 5 models
                }
            else:
                results["local"] = {"status": "error", "message": f"HTTP {response.status_code}"}
        except Exception as e:
            results["local"] = {"status": "error", "message": str(e)}
    
    logger.info(f"Connection test results for user {user_id}: {results}")
    return results

>>>>>>> 8f285fa5da2353068181e4ccb6a4047063a71a4e
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
        audio_prompt_path = req.audio_prompt or HARVIS_VOICE_PATH
        if not os.path.isfile(audio_prompt_path):
            logger.warning(
                "Audio prompt %s not found, falling back to default voice.",
                audio_prompt_path,
            )
            audio_prompt_path = None

        sr, wav = generate_speech_optimized(
            text=req.text,
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

# ─── n8n Automation Endpoints ─────────────────────────────────────────────────

@app.post("/api/n8n-automation", tags=["n8n-automation"])
async def n8n_automation_legacy(
    request: N8nAutomationRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Legacy n8n automation endpoint for backwards compatibility
    """
    return await create_n8n_automation(request, current_user)

@app.post("/api/n8n/automate", tags=["n8n-automation"])
async def create_n8n_automation(
    request: N8nAutomationRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Create n8n workflow from natural language prompt using AI
    
    This endpoint allows users to describe automation workflows in natural language
    and automatically generates corresponding n8n workflows.
    """
    if not n8n_automation_service:
        raise HTTPException(status_code=503, detail="n8n automation service not available")
    
    try:
        logger.info(f"n8n automation request from user {current_user.username}: {request.prompt[:100]}...")
        
        result = await n8n_automation_service.process_automation_request(
            request, user_id=current_user.id
        )
        
        if result.get("success"):
            logger.info(f"✅ n8n automation successful: {result['workflow']['name']}")
            return {
                "success": True,
                "message": f"Created workflow: {result['workflow']['name']}",
                "workflow": result["workflow"],
                "analysis": result.get("analysis", {}),
                "execution_time": result.get("execution_time", 0)
            }
        else:
            logger.warning(f"❌ n8n automation failed: {result.get('error', 'Unknown error')}")
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "suggestions": result.get("suggestions", [])
            }
    
    except Exception as e:
        logger.error(f"n8n automation endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/n8n/workflow", tags=["n8n-automation"])
async def create_simple_workflow(
    request: CreateWorkflowRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Create simple n8n workflow from template
    
    Creates workflows using predefined templates with specific parameters.
    """
    if not n8n_automation_service:
        raise HTTPException(status_code=503, detail="n8n automation service not available")
    
    try:
        logger.info(f"Creating simple n8n workflow '{request.name}' for user {current_user.username}")
        
        result = await n8n_automation_service.create_simple_workflow(
            request, user_id=current_user.id
        )
        
        if result.get("success"):
            return {
                "success": True,
                "message": f"Created workflow: {request.name}",
                "workflow": result["workflow"]
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error")
            }
    
    except Exception as e:
        logger.error(f"Simple workflow creation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/n8n/workflows", tags=["n8n-automation"])
async def list_user_n8n_workflows(
    current_user: UserResponse = Depends(get_current_user)
):
    """
    List all n8n workflows created by the current user
    """
    if not n8n_automation_service:
        raise HTTPException(status_code=503, detail="n8n automation service not available")
    
    try:
        workflows = await n8n_automation_service.list_user_workflows(current_user.id)
        return {
            "success": True,
            "workflows": workflows,
            "count": len(workflows)
        }
    
    except Exception as e:
        logger.error(f"Failed to list user workflows: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/n8n/templates", tags=["n8n-automation"])
async def list_workflow_templates():
    """
    List available n8n workflow templates
    """
    try:
        if not n8n_automation_service:
            # Return basic template info even if service not available
            from n8n.workflow_builder import WorkflowBuilder
            builder = WorkflowBuilder()
            templates = builder.list_templates()
        else:
            templates = n8n_automation_service.workflow_builder.list_templates()
        
        return {
            "success": True,
            "templates": templates,
            "count": len(templates)
        }
    
    except Exception as e:
        logger.error(f"Failed to list templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/n8n/workflow/{workflow_id}/execute", tags=["n8n-automation"])
async def execute_n8n_workflow(
    workflow_id: str,
    request: WorkflowExecutionRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Execute an n8n workflow manually
    """
    if not n8n_client:
        raise HTTPException(status_code=503, detail="n8n client not available")
    
    try:
        logger.info(f"Executing n8n workflow {workflow_id} for user {current_user.username}")
        
        # Verify user owns workflow
        if n8n_storage:
            workflow_record = await n8n_storage.get_workflow(workflow_id, current_user.id)
            if not workflow_record:
                raise HTTPException(status_code=404, detail="Workflow not found")
        
        # Execute workflow
        result = n8n_client.execute_workflow(workflow_id, request.input_data)
        
        return {
            "success": True,
            "execution_id": result.get("id"),
            "message": "Workflow execution started",
            "result": result
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Workflow execution error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/n8n/workflow/{workflow_id}/executions", tags=["n8n-automation"])
async def get_workflow_executions(
    workflow_id: str,
    limit: int = 20,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Get execution history for a workflow
    """
    if not n8n_client:
        raise HTTPException(status_code=503, detail="n8n client not available")
    
    try:
        # Verify user owns workflow
        if n8n_storage:
            workflow_record = await n8n_storage.get_workflow(workflow_id, current_user.id)
            if not workflow_record:
                raise HTTPException(status_code=404, detail="Workflow not found")
        
        executions = n8n_client.get_executions(workflow_id, limit)
        
        return {
            "success": True,
            "executions": executions,
            "count": len(executions)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get executions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/n8n/history", tags=["n8n-automation"])
async def get_automation_history(
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Get automation request history for the current user
    """
    if not n8n_automation_service:
        raise HTTPException(status_code=503, detail="n8n automation service not available")
    
    try:
        history = await n8n_automation_service.get_automation_history(current_user.id)
        return {
            "success": True,
            "history": history,
            "count": len(history)
        }
    
    except Exception as e:
        logger.error(f"Failed to get automation history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/n8n/health", tags=["n8n-automation"])
async def check_n8n_health():
    """
    Check n8n automation service health
    """
    try:
        if not n8n_automation_service:
            return {
                "status": "service_unavailable",
                "n8n_connected": False,
                "ai_service": False,
                "database_connected": False,
                "overall_health": False
            }
        
        health = await n8n_automation_service.test_connection()
        return {
            "status": "healthy" if health.get("overall_health") else "unhealthy",
            **health
        }
    
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "status": "error",
            "error": str(e),
            "n8n_connected": False,
            "ai_service": False,
            "database_connected": False,
            "overall_health": False
        }

@app.get("/api/n8n/stats", tags=["n8n-automation"])
async def get_n8n_statistics():
    """
    Get n8n workflow statistics
    
    Returns workflow count, active workflows, and total executions
    """
    try:
        if not n8n_automation_service or not n8n_automation_service.n8n_client:
            logger.warning("n8n automation service not available for stats")
            return {
                "totalWorkflows": 0,
                "activeWorkflows": 0,
                "totalExecutions": 0
            }

        # Get all workflows
        workflows = n8n_automation_service.n8n_client.get_workflows()
        total_workflows = len(workflows)
        
        # Count active workflows
        active_workflows = sum(1 for workflow in workflows if workflow.get('active', False))
        
        # Get total executions across all workflows
        total_executions = 0
        for workflow in workflows:
            try:
                workflow_id = workflow.get('id')
                if workflow_id:
                    executions = n8n_automation_service.n8n_client.get_executions(workflow_id, limit=250)
                    total_executions += len(executions)
            except Exception as e:
                logger.warning(f"Failed to get executions for workflow {workflow_id}: {e}")
                continue

        logger.info(f"n8n stats: {total_workflows} workflows, {active_workflows} active, {total_executions} executions")
        
        return {
            "totalWorkflows": total_workflows,
            "activeWorkflows": active_workflows,
            "totalExecutions": total_executions
        }
        
    except Exception as e:
        logger.error(f"Failed to get n8n statistics: {e}")
        # Return default stats on error to prevent UI from breaking
        return {
            "totalWorkflows": 0,
            "activeWorkflows": 0,
            "totalExecutions": 0
        }

@app.get("/api/n8n/workflows", tags=["n8n-automation"])
async def get_n8n_workflows():
    """
    Get n8n workflows with execution counts
    
    Returns list of workflows with details and execution counts
    """
    try:
        if not n8n_automation_service or not n8n_automation_service.n8n_client:
            logger.warning("n8n automation service not available for workflows")
            return {
                "workflows": []
            }

        # Get all workflows
        workflows = n8n_automation_service.n8n_client.get_workflows()
        
        # Enhance workflows with execution counts
        enhanced_workflows = []
        for workflow in workflows:
            try:
                workflow_id = workflow.get('id')
                execution_count = 0
                
                if workflow_id:
                    executions = n8n_automation_service.n8n_client.get_executions(workflow_id, limit=250)
                    execution_count = len(executions)
                
                enhanced_workflow = {
                    "id": workflow.get('id'),
                    "name": workflow.get('name', f'Workflow {workflow.get("id", "Unknown")}'),
                    "description": workflow.get('description', 'n8n automation workflow'),
                    "active": workflow.get('active', False),
                    "executionCount": execution_count,
                    "createdAt": workflow.get('createdAt'),
                    "updatedAt": workflow.get('updatedAt'),
                    "tags": workflow.get('tags', [])
                }
                enhanced_workflows.append(enhanced_workflow)
                
            except Exception as e:
                logger.warning(f"Failed to enhance workflow {workflow.get('id')}: {e}")
                # Add workflow without execution count
                enhanced_workflows.append({
                    "id": workflow.get('id'),
                    "name": workflow.get('name', f'Workflow {workflow.get("id", "Unknown")}'),
                    "description": workflow.get('description', 'n8n automation workflow'),
                    "active": workflow.get('active', False),
                    "executionCount": 0
                })

        logger.info(f"n8n workflows: returning {len(enhanced_workflows)} workflows")
        
        return {
            "workflows": enhanced_workflows
        }
        
    except Exception as e:
        logger.error(f"Failed to get n8n workflows: {e}")
        # Return empty workflows list on error
        return {
            "workflows": []
        }

# ─── Vector Database Enhanced n8n Endpoints ───────────────────────────────────────

# Initialize AI agent (will be set up in startup event)
n8n_ai_agent = None

@app.post("/api/n8n/ai-automate", tags=["n8n-ai-automation"])
async def create_n8n_automation_with_ai(
    request: N8nAutomationRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Create n8n workflow using AI with vector database context
    
    This enhanced endpoint uses vector search to find similar workflows
    and provides better context to the AI for creating more accurate workflows.
    """
    if not n8n_ai_agent:
        raise HTTPException(status_code=503, detail="n8n AI agent not available")
    
    try:
        logger.info(f"🧠 AI-enhanced n8n automation request from user {current_user.username}: {request.prompt[:100]}...")
        
        # Process request with AI agent and vector context
        result = await n8n_ai_agent.process_automation_request_with_context(
            request, user_id=current_user.id
        )
        
        if result.get("success"):
            logger.info(f"✅ AI-enhanced n8n automation successful: {result['workflow']['name']}")
            return {
                "success": True,
                "message": f"Created workflow with AI assistance: {result['workflow']['name']}",
                "workflow": result["workflow"],
                "analysis": result.get("analysis", {}),
                "ai_context": result.get("ai_context", {}),
                "execution_time": result.get("execution_time", 0)
            }
        else:
            logger.warning(f"❌ AI-enhanced n8n automation failed: {result.get('error', 'Unknown error')}")
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "suggestions": result.get("suggestions", []),
                "fallback_used": result.get("fallback_used", False)
            }
    
    except Exception as e:
        logger.error(f"AI-enhanced n8n automation endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/n8n/search-examples", tags=["n8n-ai-automation"])
async def search_workflow_examples(
    query: str,
    limit: int = 5,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Search for workflow examples in the vector database
    """
    if not n8n_ai_agent:
        raise HTTPException(status_code=503, detail="n8n AI agent not available")
    
    try:
        logger.info(f"🔍 Searching workflow examples for query: {query}")
        
        result = await n8n_ai_agent.search_workflow_examples(query, limit)
        
        return {
            "success": result.get("success", False),
            "query": query,
            "examples": result.get("results", []),
            "count": result.get("count", 0),
            "error": result.get("error")
        }
    
    except Exception as e:
        logger.error(f"Workflow search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/n8n/workflow-insights", tags=["n8n-ai-automation"])
async def get_workflow_insights(
    workflow_data: Dict[str, Any],
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Get AI insights about a workflow using vector database
    """
    if not n8n_ai_agent:
        raise HTTPException(status_code=503, detail="n8n AI agent not available")
    
    try:
        logger.info(f"🔍 Getting insights for workflow: {workflow_data.get('name', 'unnamed')}")
        
        insights = await n8n_ai_agent.get_workflow_insights(workflow_data)
        
        return {
            "success": True,
            "insights": insights
        }
    
    except Exception as e:
        logger.error(f"Workflow insights error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/n8n/vector-db/health", tags=["n8n-ai-automation"])
async def check_vector_db_health():
    """
    Check the health of the vector database service
    """
    try:
        if not n8n_ai_agent:
            return {
                "status": "service_unavailable",
                "vector_database": {"status": "not_initialized"},
                "overall_health": False
            }
        
        health = await n8n_ai_agent.health_check()
        return health
    
    except Exception as e:
        logger.error(f"Vector DB health check error: {e}")
        return {
            "status": "error",
            "error": str(e),
            "overall_health": False
        }

@app.get("/api/n8n/vector-db/stats", tags=["n8n-ai-automation"])
async def get_vector_db_stats():
    """
    Get statistics about the vector database collection
    """
    try:
        if not n8n_ai_agent:
            return {
                "error": "AI agent not available",
                "stats": {}
            }
        
        stats = await n8n_ai_agent.vector_db.get_collection_stats()
        return {
            "success": True,
            "stats": stats
        }
    
    except Exception as e:
        logger.error(f"Vector DB stats error: {e}")
        return {
            "success": False,
            "error": str(e),
            "stats": {}
        }

# ─── Advanced Research Endpoints ─────────────────────────────────────────────

class StreamingResearchRequest(BaseModel):
    """Request for streaming research"""
    query: str
    model: str = "mistral"
    enable_verification: bool = True

class ResearchStatsResponse(BaseModel):
    """Research system statistics"""
    pipeline_stats: dict
    cache_stats: dict
    system_info: dict

@app.post("/api/research/stream", tags=["research"])
async def streaming_research(req: StreamingResearchRequest):
    """
    Streaming research endpoint with real-time progress events
    """
    try:
        logger.info(f"🌊 Starting streaming research for: {req.query}")
        
        response = await async_research_agent(
            query=req.query,
            model=req.model,
            enable_streaming=True
        )
        
        if hasattr(response, '__aiter__'):
            # Return streaming response
            from fastapi.responses import StreamingResponse
            import json
            
            async def generate_stream():
                async for chunk in response:
                    # Format as server-sent events
                    if isinstance(chunk, str):
                        yield f"data: {json.dumps({'type': 'content', 'data': chunk})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'event', 'data': str(chunk)})}\n\n"
                
                # Send completion event
                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
            
            return StreamingResponse(
                generate_stream(),
                media_type="text/plain",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Content-Type": "text/event-stream"
                }
            )
        else:
            # Fallback to regular response
            return {"content": response, "streaming": False}
            
    except Exception as e:
        logger.error(f"Streaming research error: {e}")
        return {"error": f"Streaming research failed: {str(e)}"}

@app.post("/api/research/advanced-fact-check", tags=["research"])
async def advanced_fact_check(claim: str, model: str = "mistral"):
    """
    Advanced fact-checking with authority scoring and evidence analysis
    """
    try:
        logger.info(f"🔍 Advanced fact-check for: {claim}")
        
        result = await async_fact_check_agent(claim, model)
        
        return {
            "claim": claim,
            "analysis": result,
            "model_used": model,
            "advanced": True,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Advanced fact-check error: {e}")
        return {"error": f"Advanced fact-check failed: {str(e)}"}

@app.post("/api/research/advanced-compare", tags=["research"])
async def advanced_compare(topics: List[str], context: str = None, model: str = "mistral"):
    """
    Advanced comparison with structured analysis
    """
    try:
        if len(topics) < 2:
            return {"error": "At least 2 topics required for comparison"}
        
        logger.info(f"🔄 Advanced comparison of: {topics}")
        
        result = await async_comparative_research_agent(topics, model, context)
        
        return {
            "topics": topics,
            "context": context,
            "analysis": result,
            "model_used": model,
            "advanced": True,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Advanced comparison error: {e}")
        return {"error": f"Advanced comparison failed: {str(e)}"}

@app.get("/api/research/stats", response_model=ResearchStatsResponse, tags=["research"])
async def research_stats():
    """
    Get research system statistics and performance metrics
    """
    try:
        stats = get_research_agent_stats()
        
        # Add cache stats if available
        try:
            from research.cache.http_cache import get_cache
            cache = get_cache()
            cache_stats = cache.get_cache_info()
        except Exception:
            cache_stats = {"error": "Cache stats unavailable"}
        
        # System info
        import psutil
        system_info = {
            "memory_usage": psutil.virtual_memory().percent,
            "cpu_usage": psutil.cpu_percent(),
            "disk_usage": psutil.disk_usage('/').percent
        }
        
        return ResearchStatsResponse(
            pipeline_stats=stats.get("advanced_pipeline_stats", {}),
            cache_stats=cache_stats,
            system_info=system_info
        )
        
    except Exception as e:
        logger.error(f"Research stats error: {e}")
        return {"error": f"Could not get research stats: {str(e)}"}

@app.get("/api/research/health", tags=["research"])
async def research_health_check():
    """
    Health check for research system components
    """
    try:
        health = {
            "status": "healthy",
            "components": {
                "web_search": "available",
                "llm_client": "available", 
                "cache": "available",
                "advanced_pipeline": "available"
            },
            "timestamp": datetime.now().isoformat()
        }
        
        # Test basic functionality
        try:
            stats = get_research_agent_stats()
            health["components"]["stats"] = "available"
        except Exception:
            health["components"]["stats"] = "unavailable"
            health["status"] = "degraded"
        
        return health
        
    except Exception as e:
        logger.error(f"Research health check error: {e}")
        return {
            "status": "unhealthy", 
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
# ─── Vibe Coding Endpoints ─────────────────────────────────────────────────────

# Vibe coding endpoint moved to vibecoding.commands

# Voice transcribe endpoint moved to vibecoding.commands

# Run command endpoint moved to vibecoding.commands

# Save file endpoint moved to vibecoding.commands

# ─── Vibe Agent Helper Functions moved to vibecoding.core ─────────────────────

