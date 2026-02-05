from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    UploadFile,
    File,
    WebSocket,
    Depends,
    Form,
)
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.websockets import WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
import uvicorn, os, sys, tempfile, uuid, base64, io, logging, re, requests, random, json, httpx
from PIL import Image

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
from vison_models.llm_connector import (
    query_qwen,
    query_llm,
    load_qwen_model,
    unload_qwen_model,
    unload_ollama_model,
)

# Import vibecoding routers
from vibecoding import (
    sessions_router,
    models_router,
    execution_router,
    files_router,
    commands_router,
    containers_router,
)
from vibecoding.core import initialize_vibe_agent
from file_processing import extract_text_from_file

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

# Images storage directory (mounted via PVC in K8s)
IMAGES_DIR = os.getenv("IMAGES_DIR", "/app/images")
os.makedirs(IMAGES_DIR, exist_ok=True)
print(f"Images directory: {IMAGES_DIR}")
security = HTTPBearer(auto_error=False)

# Database connection
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database"
)


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


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
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
    pool = getattr(request.app.state, "pg_pool", None)
    if pool:
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT id, username, email, avatar FROM users WHERE id = $1", user_id
            )
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
            user = await conn.fetchrow(
                "SELECT id, username, email, avatar FROM users WHERE id = $1", user_id
            )
            if user is None:
                logger.error(f"User not found for ID: {user_id}")
                raise credentials_exception
            logger.info(f"User found: {dict(user)}")
            return UserResponse(**dict(user))
        finally:
            await conn.close()


# ─── Model Management -----------------------------------------------------------
from model_manager import (
    unload_models,
    unload_all_models,
    reload_models_if_needed,
    log_gpu_memory,
    get_tts_model,
    get_whisper_model,
    generate_speech,
    wait_for_vram,
    transcribe_with_whisper_optimized,
    generate_speech_optimized,
    unload_tts_model,
    unload_whisper_model,
    get_gpu_memory_stats,
    check_memory_pressure,
    auto_cleanup_if_needed,
)


# TTS Helper Function with graceful error handling
def safe_generate_speech_optimized(
    text,
    audio_prompt=None,
    exaggeration=0.5,
    temperature=0.3,
    cfg_weight=0.7,
    auto_unload=True,
):
    """Generate speech with graceful error handling - never crashes the app"""
    try:
        result = generate_speech_optimized(
            text,
            audio_prompt,
            exaggeration,
            temperature,
            cfg_weight,
            auto_unload=auto_unload,
        )
        if result is None or result == (None, None):
            logger.warning("⚠️ TTS unavailable - skipping audio generation")
            return None, None
        return result
    except Exception as tts_e:
        logger.error(f"❌ TTS generation failed gracefully: {tts_e}")
        logger.warning("⚠️ Continuing without TTS - chat will work without audio")
        return None, None


def safe_save_audio(sr, wav, prefix="response"):
    """Safely save audio to file, returning filepath or None if TTS unavailable"""
    if sr is None or wav is None:
        logger.warning("⚠️ TTS unavailable - no audio to save")
        return None

    try:
        filename = f"{prefix}_{uuid.uuid4()}.wav"
        filepath = os.path.join(tempfile.gettempdir(), filename)
        sf.write(filepath, wav, sr)
        logger.info("Audio written to %s", filepath)
        return f"/api/audio/{filename}"
    except Exception as e:
        logger.error(f"❌ Failed to save audio file: {e}")
        return None


from chat_history_module import (
    ChatHistoryManager,
    ChatMessage,
    ChatSession,
    CreateSessionRequest,
    CreateMessageRequest,
    MessageHistoryResponse,
    SessionListResponse,
    SessionNotFoundError,
    ChatHistoryError,
)
from uuid import UUID
import logging
import time

# Vibe agent is now handled in vibecoding.core module

# ─── RAG Corpus Setup ─────────────────────────────────────────────────────────
try:
    from rag_corpus import (
        rag_router,
        initialize_rag_corpus,
        LocalRAGRetriever,
        MultiCollectionRetriever,
        VectorDBAdapter,
        EmbeddingAdapter,
        get_all_vectordb_adapters,
        get_all_embedding_adapters,
        get_config_manager_instance,
        EMBEDDING_COLLECTIONS,
    )

    RAG_CORPUS_AVAILABLE = True
except ImportError as e:
    logging.warning(f"RAG corpus module not available: {e}")
    RAG_CORPUS_AVAILABLE = False
    LocalRAGRetriever = None

# Global RAG retriever (initialized in lifespan)
local_rag_retriever = None

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
    logger.warning(
        "⚠️ python-dotenv not installed, environment variables must be passed via Docker"
    )

# ─── Initialize vibe agent ─────────────────────────────────────────────────────
# Vibe agent initialization moved to vibecoding.core module
initialize_vibe_agent(project_dir=os.getcwd())

# ─── Additional logging setup ──────────────────────────────────────────────────
if "logger" not in locals():
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
    global db_pool, chat_history_manager
    try:
        # Fix database hostname: use pgsql-db instead of pgsql
        database_url = os.getenv(
            "DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database"
        )
        app.state.pg_pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=1,
            max_size=10,
            command_timeout=30,  # Increased from 5 to 30 seconds
        )
        logger.info("✅ Database connection pool created")

        # Initialize ChatHistoryManager
        db_pool = app.state.pg_pool
        chat_history_manager = ChatHistoryManager(db_pool)
        logger.info("✅ ChatHistoryManager initialized")

        # Initialize global RAG retriever if available
        if RAG_CORPUS_AVAILABLE:
            global local_rag_retriever
            try:
                # Initialize RAG corpus services first to setup globals
                logger.info("🔄 Initializing RAG corpus services...")
                rag_initialized = await initialize_rag_corpus(app.state.pg_pool)

                if rag_initialized:
                    logger.info("✅ RAG corpus services initialized successfully")

                    # Get adapters and config from initialized module
                    vectordb_adapters = get_all_vectordb_adapters()
                    embedding_adapters = get_all_embedding_adapters()
                    config_mgr = get_config_manager_instance()

                    # Build mappings
                    source_model_mapping = config_mgr.get_source_model_mapping()
                    model_collection_mapping = EMBEDDING_COLLECTIONS

                    # Initialize multi-collection retriever
                    local_rag_retriever = MultiCollectionRetriever(
                        vectordb_adapters=vectordb_adapters,
                        embedding_adapters=embedding_adapters,
                        source_to_model=source_model_mapping,
                        model_to_collection=model_collection_mapping,
                        default_k=5,
                        score_threshold=0.5,
                    )
                    logger.info("✅ Global Multi-Collection RAG retriever initialized")

                    # Verify documents are indexed
                    try:
                        total_docs = 0
                        stats_summary = {}

                        for name, adapter in vectordb_adapters.items():
                            try:
                                stats = await adapter.get_source_stats()
                                count = sum(stats.values())
                                total_docs += count
                                stats_summary[name] = stats
                            except Exception as inner_e:
                                logger.warning(
                                    f"Failed to get stats for {name}: {inner_e}"
                                )

                        logger.info(
                            f"📊 RAG: Vector DB contains {total_docs} total documents across {len(vectordb_adapters)} collections"
                        )
                        logger.info(f"📊 RAG: Stats per collection: {stats_summary}")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not get document stats: {e}")
                else:
                    logger.error("❌ RAG services failed to initialize")

            except Exception as e:
                logger.error(f"❌ Failed to initialize global RAG retriever: {e}")
                import traceback

                logger.error(traceback.format_exc())

    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        # Don't exit, allow app to start even if DB fails (will retry)

    yield

    # Shutdown: close connection pool
    if hasattr(app.state, "pg_pool"):
        await app.state.pg_pool.close()
        logger.info("✅ Database connection pool closed")


app = FastAPI(lifespan=lifespan)


# ─── Models Endpoint ──────────────────────────────────────────────────────────
@app.get("/api/models", tags=["models"])
async def list_models(current_user: UserResponse = Depends(get_current_user)):
    """
    Fetch available models from Ollama and return them for the frontend selector.
    """
    try:
        # Define Ollama Tags URL
        ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
        tags_url = f"{ollama_url}/api/tags"

        # Query Ollama
        logger.info(f"Querying Ollama models at: {tags_url}")
        async with httpx.AsyncClient() as client:
            resp = await client.get(tags_url, timeout=5.0)

        if resp.status_code != 200:
            logger.error(f"Ollama returned status {resp.status_code}")
            raise HTTPException(
                status_code=502, detail="Failed to fetch models from Ollama"
            )

        data = resp.json()
        models = data.get("models", [])

        # Format for frontend
        formatted_models = []
        for m in models:
            # Parse size (bytes -> GB)
            size_gb = m.get("size", 0) / (1024**3)
            size_str = f"{size_gb:.1f}GB"

            formatted_models.append(
                {
                    "name": m.get("name"),
                    "displayName": m.get("name").split(":")[0],  # Simple display name
                    "size": size_str,
                    "status": "available",
                }
            )

        # Sort by name
        formatted_models.sort(key=lambda x: x["name"])

        return {"models": formatted_models}

    except Exception as e:
        logger.error(f"Error fetching models: {e}")
        # Return fallback models if Ollama is down, so UI implies offline but doesn't crash
        return {
            "models": [
                {
                    "name": "mistral",
                    "displayName": "Mistral (Offline)",
                    "status": "offline",
                },
                {
                    "name": "llama3",
                    "displayName": "Llama 3 (Offline)",
                    "status": "offline",
                },
            ]
        }


# ─── Middleware ────────────────────────────────────────────────────────────────

# CORS Middleware must be added before routes
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://harvis.dulc3.tech",
        "https://harvis.dulc3.tech",
        "http://localhost:9000",  # Main nginx proxy access point
        "http://127.0.0.1:9000",  # Main nginx proxy access point
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://frontend:3000",  # Docker network
        "http://nginx-proxy:80",  # Docker network nginx
        "http://localhost:8000",  # Backend self
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

# Include RAG corpus router
if RAG_CORPUS_AVAILABLE:
    app.include_router(rag_router)

# ─── Device & models -----------------------------------------------------------
device = 0 if torch.cuda.is_available() else -1
logger.info("Using device: %s", "cuda" if device == 0 else "cpu")


# ─── Config --------------------------------------------------------------------

LOCAL_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
API_KEY = os.getenv("OLLAMA_API_KEY", "key")
DEFAULT_MODEL = "llama3.2:3b"

# External Ollama endpoint (for large models hosted elsewhere)
# NOTE: Set to empty string by default - external routing only when explicitly configured
EXTERNAL_OLLAMA_URL = os.getenv("EXTERNAL_OLLAMA_URL", "")
EXTERNAL_OLLAMA_API_KEY = os.getenv("EXTERNAL_OLLAMA_API_KEY", "")

# Models cache for routing decisions
# Only models discovered from the external endpoint will be added here
EXTERNAL_MODELS_CACHE = set()


def make_ollama_request(
    endpoint, payload, timeout=3600, user_settings=None, stream=False
):
    """Make a POST request to Ollama with automatic routing for external models.

    Args:
        endpoint: Ollama API endpoint (e.g., '/api/chat')
        payload: Request payload dict
        timeout: Request timeout in seconds
        user_settings: Optional dict with user's Ollama settings (cloud_url, local_url, api_key, preferred_endpoint)
                      If None, uses global env vars
        stream: Whether to stream the response (default: False)

    Returns:
        The response object from the successful request.
    """
    # Check if the model should be routed to the external endpoint
    model_name = payload.get("model", "")
    is_external_model = model_name in EXTERNAL_MODELS_CACHE

    if is_external_model and EXTERNAL_OLLAMA_URL and EXTERNAL_OLLAMA_API_KEY:
        # Route to external Ollama (e.g., coyotedev.ngrok.app)
        try:
            headers = {
                "Authorization": f"Bearer {EXTERNAL_OLLAMA_API_KEY}",
                "ngrok-skip-browser-warning": "true",
                "User-Agent": "Harvis-Backend",
            }
            logger.info(
                "🌐 Using external Ollama for %s: %s (stream=%s)",
                model_name,
                EXTERNAL_OLLAMA_URL,
                stream,
            )
            response = requests.post(
                f"{EXTERNAL_OLLAMA_URL}{endpoint}",
                json=payload,
                headers=headers,
                timeout=timeout,
                stream=stream,
            )
            if response.status_code == 200:
                logger.info("✅ External Ollama request successful")
                return response
            else:
                logger.error(
                    "❌ External Ollama returned status %s", response.status_code
                )
                response.raise_for_status()
        except Exception as e:
            logger.error("❌ External Ollama request failed: %s", e)
            raise

    # Use user settings if provided, otherwise use global defaults
    if user_settings:
        local_url = user_settings.get("local_url") or LOCAL_OLLAMA_URL
    else:
        local_url = LOCAL_OLLAMA_URL

    # Try local Ollama
    try:
        logger.info("🏠 Using local Ollama: %s", local_url)
        response = requests.post(
            f"{local_url}{endpoint}", json=payload, timeout=timeout, stream=stream
        )
        if response.status_code == 200:
            logger.info("✅ Local Ollama request successful")
            return response
        else:
            logger.error("❌ Local Ollama returned status %s", response.status_code)
            response.raise_for_status()
    except Exception as e:
        logger.error("❌ Local Ollama request failed: %s", e)
        raise


# ─── SSE Heartbeat Constants ──────────────────────────────────────────────────
HEARTBEAT_INTERVAL = 10  # Send heartbeat every 10 seconds to keep connection alive
MAX_RESPONSE_SIZE = int(
    os.getenv("MAX_RESPONSE_SIZE", "100000")
)  # Default 100k chars (~20k words)


async def stream_ollama_chunks(endpoint, payload, timeout=3600):
    """
    Stream chunks from Ollama using async httpx.
    Replaces the threading/queue implementation for better stability.
    """
    import httpx

    # Routing logic
    model_name = payload.get("model", "")
    is_external_model = model_name in EXTERNAL_MODELS_CACHE

    # Determine URL and headers
    if is_external_model and EXTERNAL_OLLAMA_URL and EXTERNAL_OLLAMA_API_KEY:
        url = f"{EXTERNAL_OLLAMA_URL}{endpoint}"
        headers = {
            "Authorization": f"Bearer {EXTERNAL_OLLAMA_API_KEY}",
            "ngrok-skip-browser-warning": "true",
            "User-Agent": "Harvis-Backend",
        }
        logger.info(f"🌐 Using external Ollama for {model_name}: {url}")
    else:
        # User settings override (if applicable - currently not passed to this func)
        url = f"{LOCAL_OLLAMA_URL}{endpoint}"
        headers = {}
        logger.info(f"🏠 Using local Ollama: {url}")

    try:
        # Increase timeout for connection and reading
        timeout_config = httpx.Timeout(timeout, connect=60.0)

        async with httpx.AsyncClient(timeout=timeout_config) as client:
            async with client.stream(
                "POST", url, json=payload, headers=headers
            ) as response:
                if response.status_code != 200:
                    # Read error body
                    error_text = await response.aread()
                    error_msg = f"Ollama error {response.status_code}: {error_text.decode('utf-8', errors='ignore')[:200]}"
                    raise Exception(error_msg)

                # Stream lines
                async for line in response.aiter_lines():
                    if line:
                        # Yield bytes to match existing consumer logic
                        yield line.encode("utf-8")

    except httpx.ReadTimeout:
        logger.error(f"❌ Ollama read timeout after {timeout}s")
        raise Exception("Ollama generation timed out")
    except Exception as e:
        logger.error(f"❌ Async stream error: {e}")
        raise


async def run_ollama_with_heartbeats(endpoint: str, payload: dict, timeout: int = 3600):
    """
    Run an Ollama request in a background thread while yielding heartbeats.
    This prevents Zen browser (and others) from killing the connection due to idle timeout.

    Yields:
        dict: Either a heartbeat event or the final result
    """
    import asyncio
    import concurrent.futures

    # Create a thread pool executor for the blocking Ollama request
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    # Submit the Ollama request to run in a thread
    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(
        executor, make_ollama_request, endpoint, payload, timeout
    )

    heartbeat_count = 0
    start_time = asyncio.get_event_loop().time()

    while True:
        try:
            # Wait for the result with a timeout of HEARTBEAT_INTERVAL seconds
            result = await asyncio.wait_for(
                asyncio.shield(future), timeout=HEARTBEAT_INTERVAL
            )

            # Got the result - return it
            elapsed = asyncio.get_event_loop().time() - start_time
            logger.info(
                f"💓 Ollama completed after {elapsed:.1f}s ({heartbeat_count} heartbeats sent)"
            )

            yield {"type": "result", "data": result}
            executor.shutdown(wait=False)
            return

        except asyncio.TimeoutError:
            # Heartbeat time - send a keepalive
            heartbeat_count += 1
            elapsed = asyncio.get_event_loop().time() - start_time
            logger.info(f"💓 Heartbeat #{heartbeat_count} ({elapsed:.1f}s elapsed)")

            yield {
                "type": "heartbeat",
                "count": heartbeat_count,
                "elapsed": round(elapsed, 1),
            }

        except Exception as e:
            logger.error(f"❌ Ollama request failed: {e}")
            executor.shutdown(wait=False)
            raise


async def run_stt_with_heartbeats(audio_path: str):
    """
    Run STT in a background thread with heartbeats.
    """
    import asyncio
    import concurrent.futures

    # Create a thread pool executor
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    # Submit the STT task
    loop = asyncio.get_event_loop()

    def stt_task():
        return transcribe_with_whisper_optimized(audio_path)

    future = loop.run_in_executor(executor, stt_task)

    heartbeat_count = 0
    start_time = loop.time()

    while True:
        try:
            # Wait for result with timeout
            result = await asyncio.wait_for(
                asyncio.shield(future), timeout=HEARTBEAT_INTERVAL
            )

            elapsed = loop.time() - start_time
            logger.info(f"🎤 STT completed after {elapsed:.1f}s")

            yield {"type": "result", "data": result}
            executor.shutdown(wait=False)
            return

        except asyncio.TimeoutError:
            heartbeat_count += 1
            elapsed = loop.time() - start_time
            logger.info(f"💓 STT Heartbeat #{heartbeat_count} ({elapsed:.1f}s)")

            yield {
                "type": "heartbeat",
                "count": heartbeat_count,
                "elapsed": round(elapsed, 1),
            }
        except Exception as e:
            logger.error(f"❌ STT task failed: {e}")
            executor.shutdown(wait=False)
            raise


async def run_tts_with_heartbeats(
    text: str,
    audio_prompt: str,
    exaggeration: float,
    temperature: float,
    cfg_weight: float,
    auto_unload: bool,
):
    """
    Run TTS in a background thread with heartbeats.
    """
    import asyncio
    import concurrent.futures

    # Create a thread pool executor
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    # Submit the TTS task
    loop = asyncio.get_event_loop()

    def tts_task():
        return safe_generate_speech_optimized(
            text=text,
            audio_prompt=audio_prompt,
            exaggeration=exaggeration,
            temperature=temperature,
            cfg_weight=cfg_weight,
            auto_unload=auto_unload,
        )

    future = loop.run_in_executor(executor, tts_task)

    heartbeat_count = 0
    start_time = loop.time()

    while True:
        try:
            # Wait for result with timeout
            result = await asyncio.wait_for(
                asyncio.shield(future), timeout=HEARTBEAT_INTERVAL
            )

            elapsed = loop.time() - start_time
            logger.info(f"🔊 TTS completed after {elapsed:.1f}s")

            yield {"type": "result", "data": result}
            executor.shutdown(wait=False)
            return

        except asyncio.TimeoutError:
            heartbeat_count += 1
            elapsed = loop.time() - start_time
            logger.info(f"💓 TTS Heartbeat #{heartbeat_count} ({elapsed:.1f}s)")

            yield {
                "type": "heartbeat",
                "count": heartbeat_count,
                "elapsed": round(elapsed, 1),
            }
        except Exception as e:
            logger.error(f"❌ TTS task failed: {e}")
            executor.shutdown(wait=False)
            raise


def make_ollama_get_request(endpoint, timeout=10, user_settings=None):
    """Make a GET request to Ollama with automatic fallback from cloud to local.

    Args:
        endpoint: Ollama API endpoint (e.g., '/api/tags')
        timeout: Request timeout in seconds
        user_settings: Optional dict with user's Ollama settings

    Returns:
        The response object from the successful request.
    """
    # Use user settings if provided, otherwise use global defaults
    if user_settings:
        local_url = user_settings.get("local_url") or LOCAL_OLLAMA_URL
    else:
        local_url = LOCAL_OLLAMA_URL

    # Try local only
    try:
        logger.info("🏠 Using local Ollama GET: %s", local_url)
        response = requests.get(f"{local_url}{endpoint}", timeout=timeout)
        if response.status_code == 200:
            logger.info("✅ Local Ollama GET request successful")
            return response
        else:
            logger.error("❌ Local Ollama GET returned status %s", response.status_code)
            response.raise_for_status()
    except Exception as e:
        logger.error("❌ Local Ollama GET request failed: %s", e)
        raise


def get_ollama_url():
    """Return local Ollama URL."""
    return LOCAL_OLLAMA_URL


# Get the working Ollama URL for initialization
OLLAMA_URL = get_ollama_url()


# ─── Pydantic schemas ----------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []
    model: str = DEFAULT_MODEL
    session_id: Optional[str] = None  # Chat session ID for history persistence
    audio_prompt: Optional[str] = None  # overrides HARVIS_VOICE_PATH if provided
    attachments: Optional[List[Dict[str, Any]]] = None  # List of file attachments
    exaggeration: float = 0.5
    temperature: float = 0.5  # Lower temp = more stable TTS output
    cfg_weight: float = 2.0  # Higher cfg = follows text more closely
    low_vram: bool = False
    text_only: bool = False


class ResearchChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []
    model: str = DEFAULT_MODEL
    session_id: Optional[str] = None  # Chat session ID for history persistence
    enableWebSearch: bool = True
    audio_prompt: Optional[str] = None  # overrides HARVIS_VOICE_PATH if provided
    exaggeration: float = 0.5
    temperature: float = 0.5  # Lower temp = more stable TTS output
    cfg_weight: float = 2.0  # Higher cfg = follows text more closely


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


class VisionChatRequest(BaseModel):
    """Request model for Ollama vision chat (llava, moondream, etc.)"""

    message: str
    images: List[str]  # List of base64 images (data-URI or raw)
    history: List[Dict[str, Any]] = []
    model: str = "llava"  # Default to llava, user can select any VL model
    session_id: Optional[str] = None
    low_vram: bool = False
    text_only: bool = False


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
    Extract the content between thinking tags and remove them from the text.
    Supports both <think>...</think> and <thinking>...</thinking> formats.
    Returns (reasoning/thoughts, final_answer)
    """
    import re

    thoughts = ""
    remaining_text = text

    # Support both <think> and <thinking> tags (case-insensitive)
    patterns = [
        (r"<think>(.*?)</think>", "<think>", "</think>"),
        (r"<thinking>(.*?)</thinking>", "<thinking>", "</thinking>"),
    ]

    for regex_pattern, open_tag, close_tag in patterns:
        # Use regex to extract all matches (DOTALL for multiline)
        matches = re.findall(regex_pattern, remaining_text, re.DOTALL | re.IGNORECASE)
        for match in matches:
            thought_content = match.strip()
            if thought_content:
                thoughts += thought_content + "\n\n"

        # Remove tags and content from text
        remaining_text = re.sub(
            regex_pattern, "", remaining_text, flags=re.DOTALL | re.IGNORECASE
        )

    # Clean up the final answer
    final_answer = remaining_text.strip()
    reasoning = thoughts.strip()

    logger.info(
        f"Separated reasoning: {len(reasoning)} chars, final answer: {len(final_answer)} chars"
    )

    return reasoning, final_answer


def has_reasoning_content(text: str) -> bool:
    """Check if text contains reasoning markers (supports both <think> and <thinking> tags)"""
    text_lower = text.lower()
    return ("<think>" in text_lower and "</think>" in text_lower) or (
        "<thinking>" in text_lower and "</thinking>" in text_lower
    )


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
@app.post(
    "/api/chat-history/sessions", response_model=ChatSession, tags=["chat-history"]
)
async def create_chat_session(
    request: CreateSessionRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """Create a new chat session"""
    try:
        session = await chat_history_manager.create_session(
            user_id=current_user.id, title=request.title, model_used=request.model_used
        )
        return session
    except Exception as e:
        logger.error(f"Error creating chat session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create chat session")


@app.get(
    "/api/chat-history/sessions",
    response_model=List[ChatSession],
    tags=["chat-history"],
)
async def get_user_chat_sessions(
    limit: int = 50,
    offset: int = 0,
    current_user: UserResponse = Depends(get_current_user),
):
    """Get all chat sessions for the current user"""
    try:
        sessions_response = await chat_history_manager.get_user_sessions(
            user_id=current_user.id, limit=limit, offset=offset
        )
        return sessions_response.sessions
    except Exception as e:
        logger.error(f"Error getting user sessions: {e}")
        raise HTTPException(status_code=500, detail="Failed to get chat sessions")


@app.get(
    "/api/chat-history/sessions/{session_id}",
    response_model=MessageHistoryResponse,
    tags=["chat-history"],
)
async def get_session_messages(
    session_id: str,
    limit: int = 100,
    offset: int = 0,
    current_user: UserResponse = Depends(get_current_user),
):
    """Get messages for a specific chat session"""
    try:
        # Convert string session_id to UUID
        session_uuid = UUID(session_id)
        logger.info(
            f"Getting messages for session {session_uuid}, user {current_user.id}"
        )
        response = await chat_history_manager.get_session_messages(
            session_id=session_uuid, user_id=current_user.id, limit=limit, offset=offset
        )
        logger.info(
            f"Retrieved {len(response.messages)} messages for session {session_uuid}"
        )

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
    current_user: UserResponse = Depends(get_current_user),
):
    """Update chat session title"""
    try:
        # Convert string session_id to UUID
        session_uuid = UUID(session_id)
        success = await chat_history_manager.update_session_title(
            session_id=session_uuid, user_id=current_user.id, title=request.title
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
    session_id: str, current_user: UserResponse = Depends(get_current_user)
):
    """Delete a chat session"""
    try:
        # Convert string session_id to UUID
        session_uuid = UUID(session_id)
        success = await chat_history_manager.delete_session(
            session_id=session_uuid, user_id=current_user.id
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
    session_id: str, current_user: UserResponse = Depends(get_current_user)
):
    """Clear all messages from a chat session"""
    try:
        # Convert string session_id to UUID
        session_uuid = UUID(session_id)
        deleted_count = await chat_history_manager.clear_session_messages(
            session_id=session_uuid, user_id=current_user.id
        )
        return {"success": True, "message": f"Deleted {deleted_count} messages"}
    except Exception as e:
        logger.error(f"Error clearing session messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear session messages")


@app.get(
    "/api/chat-history/search", response_model=List[ChatMessage], tags=["chat-history"]
)
async def search_messages(
    query: str,
    session_id: Optional[str] = None,
    limit: int = 50,
    current_user: UserResponse = Depends(get_current_user),
):
    """Search messages by content"""
    try:
        messages = await chat_history_manager.search_messages(
            user_id=current_user.id, query=query, session_id=session_id, limit=limit
        )
        return messages
    except Exception as e:
        logger.error(f"Error searching messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to search messages")


@app.get("/api/chat-history/stats", tags=["chat-history"])
async def get_user_chat_stats(current_user: UserResponse = Depends(get_current_user)):
    """Get user chat statistics"""
    try:
        stats = await chat_history_manager.get_user_stats(current_user.id)
        return stats
    except Exception as e:
        logger.error(f"Error getting user stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user stats")


@app.post(
    "/api/chat-history/messages", response_model=ChatMessage, tags=["chat-history"]
)
async def add_message_to_session(
    message_request: CreateMessageRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """Add a message to a chat session"""
    try:
        # Verify the user owns the session
        session = await chat_history_manager.get_session(
            message_request.session_id, current_user.id
        )
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
            metadata=message_request.metadata,
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
    pool = getattr(app_request.app.state, "pg_pool", None)

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
            request.email,
            request.username,
        )
        if existing_user:
            raise HTTPException(
                status_code=409,
                detail="User with this email or username already exists",
            )

        # Hash password and create user
        hashed_password = get_password_hash(request.password)
        user_id = await conn.fetchval(
            "INSERT INTO users (username, email, password) VALUES ($1, $2, $3) RETURNING id",
            request.username,
            request.email,
            hashed_password,
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
    pool = getattr(app_request.app.state, "pg_pool", None)

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
            "SELECT id, password FROM users WHERE email = $1", request.email
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

        response = JSONResponse(
            content={"access_token": access_token, "token_type": "bearer"}
        )
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
async def get_current_user_info(current_user: UserResponse = Depends(get_current_user)):
    """Get current user info"""
    return current_user


@app.get("/api/auth/stats", tags=["auth"])
async def get_authentication_stats():
    """Get authentication performance statistics"""
    return get_auth_stats()


# Import new modules


# ── Auto-Research Detection for Perplexity-style behavior ──────────────────────
def should_auto_research(message: str) -> bool:
    """
    Detect if a message should trigger automatic web research (Perplexity-style).
    Returns True for freshness/recommendation queries, False for conceptual questions.
    """
    msg_lower = message.lower()

    # Keywords that indicate need for current/fresh information
    freshness_keywords = [
        "new",
        "latest",
        "current",
        "2026",
        "2025",
        "today",
        "this week",
        "recently",
        "best",
        "top",
        "recommend",
        "compare",
        "vs",
        "which should",
        "roadmap",
        "release",
        "what changed",
        "update",
        "version",
        "trending",
        "popular",
        "modern",
        "state of the art",
        "sota",
    ]

    # Keywords that indicate conceptual questions (don't need web search)
    conceptual_keywords = [
        "explain",
        "what is",
        "how does",
        "define",
        "tutorial",
        "teach me",
        "understand",
        "concept",
        "basics",
        "fundamentals",
    ]

    # Explicit research requests always trigger
    explicit_research = [
        "search",
        "look up",
        "find sources",
        "research",
        "browse",
        "check online",
        "google",
        "web search",
    ]

    # Check for explicit research request first
    for keyword in explicit_research:
        if keyword in msg_lower:
            logger.info(f"🔍 Auto-research triggered by explicit keyword: '{keyword}'")
            return True

    # Check for conceptual questions (skip research)
    for keyword in conceptual_keywords:
        if keyword in msg_lower:
            # But override if freshness is also present
            has_freshness = any(fk in msg_lower for fk in freshness_keywords)
            if not has_freshness:
                logger.info(f"📚 Conceptual question detected, skipping auto-research")
                return False

    # Check for freshness keywords
    for keyword in freshness_keywords:
        if keyword in msg_lower:
            logger.info(f"🔍 Auto-research triggered by freshness keyword: '{keyword}'")
            return True

    return False


# ── Local RAG Context Helper ────────────────────────────────────────────────────
async def get_local_rag_context(query: str, max_length: int = 2000) -> str:
    """
    Retrieve relevant context from the local RAG corpus.
    Returns formatted context string or empty string if unavailable.
    """
    logger.info(f"🔍 RAG: Starting context retrieval for query: '{query[:100]}...'")

    if local_rag_retriever is None:
        logger.error("❌ RAG: local_rag_retriever is None - not initialized!")
        return ""

    try:
        logger.info(
            f"🔍 RAG: Retriever initialized, querying with k=3, max_length={max_length}"
        )

        # First, let's check if we can retrieve raw results
        raw_results = await local_rag_retriever.retrieve(query, k=3)
        logger.info(f"🔍 RAG: Retrieved {len(raw_results)} raw results from vector DB")

        if raw_results:
            for idx, result in enumerate(raw_results):
                source = result.metadata.get("source", "unknown")
                score = getattr(result, "score", "N/A")
                logger.info(
                    f"🔍 RAG: Result {idx}: source={source}, score={score}, text_length={len(result.text)}"
                )
        else:
            logger.warning(
                "⚠️ RAG: No results returned from vector DB - documents may not be indexed or query doesn't match"
            )

        # Now get formatted context
        context = await local_rag_retriever.get_context_string(
            query=query, k=3, max_length=max_length
        )

        if context:
            logger.info(
                f"📚 RAG: Successfully formatted {len(context)} chars of context"
            )
            # Log a preview of the context
            context_preview = context[:200] + "..." if len(context) > 200 else context
            logger.info(f"📚 RAG: Context preview: {context_preview}")
        else:
            logger.warning("⚠️ RAG: Context string is empty after formatting")

        return context
    except Exception as e:
        logger.error(f"❌ RAG: Failed to get local RAG context: {e}")
        logger.exception("Full traceback:")
        return ""


@app.post("/api/chat", tags=["chat"])
async def chat(
    req: ChatRequest,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
):
    """
    Main conversational endpoint with persistent chat history.
    Now uses SSE streaming with heartbeats to prevent browser idle timeouts (Zen, etc.).

    Produces: SSE stream with status events, final event contains {history, audio_path, session_id}
    """
    import asyncio

    async def stream_chat():
        try:
            logger.info(
                f"Chat endpoint reached - User: {current_user.username}, Message: {req.message[:50]}..."
            )
            logger.info(
                f"⚙️ Mode flags - low_vram: {req.low_vram}, text_only: {req.text_only}"
            )

            # ── 0. Initial SSE event ──────────────────────────────────────────────────────
            yield f"data: {json.dumps({'status': 'starting', 'message': 'Processing your request...'})}\n\n"

            # ── 1. Process Attachments FIRST so content is available for research ──────────
            current_message_content = req.message

            if req.attachments:
                logger.info(f"Processing {len(req.attachments)} attachments")
                yield f"data: {json.dumps({'status': 'processing', 'detail': 'Processing attachments...'})}\n\n"
                attachment_text = []
                for attachment in req.attachments:
                    if attachment.get("type") == "image":
                        continue
                    file_name = attachment.get("name", "Unknown File")
                    file_type = attachment.get("mimeType", "") or attachment.get(
                        "type", ""
                    )
                    file_data = attachment.get("data", "")
                    if file_data:
                        logger.info(
                            f"Extracting text from attachment: {file_name} ({file_type})"
                        )
                        extracted = extract_text_from_file(
                            file_data, file_name if not file_type else file_type
                        )
                        if extracted:
                            attachment_text.append(
                                f"\n--- Content of {file_name} ---\n{extracted}\n--- End of {file_name} ---\n"
                            )
                if attachment_text:
                    current_message_content += "\n" + "\n".join(attachment_text)
                    logger.info(
                        f"Added {len(attachment_text)} file contents to message"
                    )

            # ── 2. Auto-Research Detection (Perplexity-style) ──────────────────────────────
            if should_auto_research(req.message):
                logger.info(
                    "🔍 Auto-research triggered, redirecting to research pipeline"
                )
                yield f"data: {json.dumps({'status': 'researching', 'detail': 'Auto-research triggered, searching the web...'})}\n\n"
                try:
                    from agent_research import research_agent

                    research_result = await run_in_threadpool(
                        research_agent,
                        current_message_content,
                        req.model,
                        use_advanced=False,
                    )

                    if "error" not in research_result:
                        analysis = research_result.get("analysis", "")
                        sources = research_result.get("sources", [])
                        videos = research_result.get("videos", [])

                        response_data = {
                            "status": "complete",
                            "response": analysis,
                            "history": req.history
                            + [
                                {"role": "user", "content": current_message_content},
                                {"role": "assistant", "content": analysis},
                            ],
                            "final_answer": analysis,
                            "auto_researched": True,
                            "sources": sources[:5],
                            "videos": videos[:6],
                            "session_id": req.session_id,
                        }

                        # Handle session creation if needed (e.g. first message)
                        saved_session_id = req.session_id
                        try:
                            # If we have a session ID, verify it
                            if saved_session_id:
                                try:
                                    from uuid import UUID

                                    if isinstance(saved_session_id, str):
                                        # Just check if it's valid, we don't need the object here
                                        UUID(saved_session_id)
                                except ValueError:
                                    saved_session_id = None

                            # Create new session if needed
                            if not saved_session_id:
                                session = await chat_history_manager.create_session(
                                    user_id=current_user.id,
                                    title="New Chat",
                                    model_used=req.model,
                                )
                                saved_session_id = str(session.id)
                                # Update response data with new session ID
                                response_data["session_id"] = saved_session_id

                            # Save user message
                            await chat_history_manager.add_message(
                                user_id=current_user.id,
                                session_id=saved_session_id,
                                role="user",
                                content=current_message_content,
                                model_used=req.model,
                                input_type="text",
                            )

                            # Prepare metadata with sources and videos
                            research_metadata = {
                                "sources": sources[:5] if sources else [],
                                "videos": videos[:6] if videos else [],
                                "auto_researched": True,
                            }

                            # Save assistant message with metadata
                            asst_msg = await chat_history_manager.add_message(
                                user_id=current_user.id,
                                session_id=saved_session_id,
                                role="assistant",
                                content=analysis,
                                model_used=req.model,
                                input_type="text",
                                metadata=research_metadata,
                            )
                            # Add message ID to response data
                            response_data["message_id"] = asst_msg.id
                            logger.info(
                                f"💾 Saved auto-research messages to session {saved_session_id} (msg_id: {asst_msg.id})"
                            )
                            logger.info(
                                f"💾 Saved auto-research messages to session {saved_session_id}"
                            )
                        except Exception as e:
                            logger.error(
                                f"Failed to save auto-research to history: {e}"
                            )

                        logger.info(
                            f"Yielding auto-research response. Analysis length: {len(analysis)} chars. JSON size: {len(json.dumps(response_data))} chars"
                        )
                        yield f"data: {json.dumps(response_data)}\n\n"
                        return
                except Exception as e:
                    logger.error(
                        f"Auto-research failed, falling back to regular chat: {e}"
                    )

            # ── 3. Handle chat session and history ──────────────────────────────────────────
            session_id = req.session_id

            if session_id:
                try:
                    from uuid import UUID

                    session_uuid = UUID(session_id)
                    recent_messages = await chat_history_manager.get_recent_messages(
                        session_id=session_uuid, user_id=current_user.id, limit=10
                    )
                except (ValueError, Exception) as e:
                    logger.error(
                        f"Invalid session_id format or error loading context: {e}"
                    )
                    recent_messages = []
                history = chat_history_manager.format_messages_for_context(
                    recent_messages
                )
                logger.info(
                    f"Using session {session_id} with {len(recent_messages)} recent messages"
                )
            else:
                history = req.history
                logger.info("No session provided, using request history")

            history = history + [{"role": "user", "content": current_message_content}]
            response_text: str

            # ── 4. Browser automation branch -------------------------------------------------
            if is_browser_command(req.message):
                yield f"data: {json.dumps({'status': 'processing', 'detail': 'Executing browser command...'})}\n\n"
                try:
                    from trash.browser import (
                        smart_url_handler,
                        search_google,
                        open_new_tab,
                    )

                    result = smart_url_handler(req.message)
                    response_text = (
                        search_google(result["query"])
                        if isinstance(result, dict) and result.get("type") == "search"
                        else open_new_tab(result)
                    )
                except Exception as e:
                    logger.error("Browser cmd failed: %s", e)
                    response_text = (
                        "¡Ay! Hubo un problema con esa acción del navegador."
                    )

            # ── 5. Gemini model branch ──────────────────────────────────────────────────────
            elif req.model == "gemini-1.5-flash":
                yield f"data: {json.dumps({'status': 'processing', 'detail': 'Querying Gemini...'})}\n\n"
                response_text = query_gemini(req.message, req.history)

            # ── 6. Ollama LLM generation branch (with heartbeats) ────────────────────────────
            else:
                system_prompt_path = os.path.join(
                    os.path.dirname(__file__), "system_prompt.txt"
                )
                try:
                    with open(system_prompt_path, "r", encoding="utf-8") as f:
                        system_prompt = f.read().strip()
                except FileNotFoundError:
                    logger.warning("system_prompt.txt not found, using default prompt")
                    system_prompt = (
                        'You are "Jarves", a voice-first local assistant. '
                        "Reply in ≤25 spoken-style words, sprinkling brief Spanish when natural, Be bilangual about 80 percent english and 20 percent spanish"
                        'Begin each answer with a short verbal acknowledgment (e.g., "Claro,", "¡Por supuesto!", "Right away").'
                    )
                OLLAMA_ENDPOINT = "/api/chat"

                is_reasoning_model = any(
                    x in req.model.lower()
                    for x in ["deepseek-r1", "r1:", "qwq", "reasoning"]
                )

                if is_reasoning_model:
                    reasoning_instruction = (
                        "\n\nIMPORTANT: When reasoning through problems, wrap your thinking process in <think>...</think> tags. "
                        "This allows your reasoning to be shown separately from your final answer. "
                        "Example:\n<think>\nLet me think about this...\n</think>\nHere is my answer."
                    )
                    system_prompt = system_prompt + reasoning_instruction
                    logger.info(
                        f"🧠 Reasoning model detected ({req.model}) - added <think> tag instructions"
                    )

                logger.info(
                    f"🤖 CHAT: About to retrieve RAG context for message: '{current_message_content[:100]}...'"
                )
                local_rag_context = await get_local_rag_context(current_message_content)

                if local_rag_context:
                    rag_instruction = (
                        "\n\n--- RELEVANT DOCUMENTATION FROM LOCAL CORPUS ---\n"
                        "The following is relevant context from indexed documentation. "
                        "Use this information to provide accurate, well-informed responses:\n\n"
                        f"{local_rag_context}\n"
                        "--- END OF DOCUMENTATION CONTEXT ---\n"
                    )
                    system_prompt = system_prompt + rag_instruction
                    logger.info(
                        f"📚 CHAT: Added {len(local_rag_context)} chars of RAG context to system prompt"
                    )
                    logger.info(
                        f"📚 CHAT: New system prompt length: {len(system_prompt)} chars"
                    )
                else:
                    logger.warning(
                        "⚠️ CHAT: No RAG context retrieved - system prompt unchanged"
                    )

                messages = [{"role": "system", "content": system_prompt}]
                for msg in history[:-1]:
                    messages.append({"role": msg["role"], "content": msg["content"]})
                messages.append({"role": "user", "content": current_message_content})

                payload = {"model": req.model, "messages": messages, "stream": True}

                # Count RAG context presence
                has_rag_context = (
                    local_rag_context is not None and len(local_rag_context) > 0
                )
                rag_status = (
                    "✅ WITH RAG context"
                    if has_rag_context
                    else "❌ WITHOUT RAG context"
                )

                logger.info(
                    f"💬 CHAT: Sending {len(messages)} messages to Ollama (including {len(history) - 1} history messages) - {rag_status}"
                )

                for idx, msg in enumerate(messages):
                    content_preview = (
                        msg["content"][:150]
                        if len(msg["content"]) > 150
                        else msg["content"]
                    )
                    # For system message, indicate if it has RAG
                    if msg["role"] == "system" and has_rag_context:
                        content_preview = (
                            "[SYSTEM PROMPT WITH RAG CONTEXT] " + content_preview
                        )
                    logger.info(
                        f"💬 CHAT: Message {idx}: role={msg['role']}, content_preview='{content_preview}...'"
                    )

                logger.info(
                    "💬 CHAT: Using model '%s' for Ollama %s",
                    req.model,
                    OLLAMA_ENDPOINT,
                )

                # ── Streaming Inference ────────────────────────────────────────────────
                yield f"data: {json.dumps({'status': 'inference', 'detail': f'Thinking with {req.model}...'})}\n\n"

                response_text = ""
                response_chunks = []
                chunk_count = 0
                all_chunk_count = (
                    0  # Track all chunks including empty ones for debugging
                )

                # Retry logic for OOM
                max_retries = 1
                for attempt in range(max_retries + 1):
                    try:
                        # Use stream=True to enable token-by-token streaming in a background thread
                        # This prevents blocking the main event loop while waiting for tokens
                        async for line in stream_ollama_chunks(
                            OLLAMA_ENDPOINT, payload, timeout=3600
                        ):
                            if line:
                                try:
                                    decoded_line = line.decode("utf-8")
                                    chunk_json = json.loads(decoded_line)
                                    all_chunk_count += 1

                                    if "error" in chunk_json:
                                        error_msg = chunk_json["error"]
                                        if (
                                            "out of memory" in error_msg.lower()
                                            and attempt < max_retries
                                        ):
                                            raise requests.exceptions.HTTPError(
                                                f"OOM: {error_msg}"
                                            )

                                        logger.error(
                                            f"Ollama streaming error: {error_msg}"
                                        )
                                        yield f"data: {json.dumps({'status': 'error', 'error': error_msg})}\n\n"
                                        return

                                    # Log first few chunks to debug empty responses
                                    if all_chunk_count <= 3:
                                        logger.info(
                                            f"📡 Ollama raw chunk #{all_chunk_count}: {str(chunk_json)[:300]}"
                                        )

                                    if "message" in chunk_json:
                                        content_chunk = chunk_json["message"].get(
                                            "content", ""
                                        )
                                        if content_chunk:
                                            # Yield token to frontend
                                            yield f"data: {json.dumps({'status': 'streaming', 'content': content_chunk})}\n\n"
                                            # Accumulate for history saving and TTS (using list for efficiency)
                                            response_chunks.append(content_chunk)
                                            chunk_count += 1

                                            # Log progress for large responses
                                            if chunk_count % 500 == 0:
                                                current_size = sum(
                                                    len(c) for c in response_chunks
                                                )
                                                logger.info(
                                                    f"📊 Response accumulation: {chunk_count} chunks, {current_size:,} chars"
                                                )

                                            # Check response size limit
                                            if chunk_count % 100 == 0:
                                                current_size = sum(
                                                    len(c) for c in response_chunks
                                                )
                                                if current_size > MAX_RESPONSE_SIZE:
                                                    logger.warning(
                                                        f"⚠️ Response exceeded {MAX_RESPONSE_SIZE:,} chars, truncating"
                                                    )
                                                    yield f"data: {json.dumps({'status': 'warning', 'message': 'Response truncated due to size limit'})}\n\n"
                                                    break

                                    if chunk_json.get("done", False):
                                        pass

                                except json.JSONDecodeError:
                                    continue

                        # If we reached here without exception, streaming succeeded
                        break

                    except Exception as e:
                        error_str = str(e).lower()
                        # Catch both 500 errors and explicit OOM messages
                        if (
                            "500" in error_str or "out of memory" in error_str
                        ) and attempt < max_retries:
                            logger.warning(
                                f"🚨 Ollama OOM detected (Attempt {attempt + 1}). Cleaning VRAM and retrying..."
                            )
                            yield f"data: {json.dumps({'status': 'processing', 'detail': 'GPU memory full, cleaning up...'})}\n\n"

                            # Aggressive cleanup
                            unload_all_models()
                            import gc

                            gc.collect()
                            if torch.cuda.is_available():
                                torch.cuda.empty_cache()

                            await asyncio.sleep(2)  # Give it a moment
                            response_chunks = []  # Reset chunks for retry
                            chunk_count = 0
                            continue
                        else:
                            logger.error(
                                f"Streaming request failed after {attempt + 1} attempts: {e}"
                            )
                            import traceback

                            logger.error(f"Full traceback: {traceback.format_exc()}")
                            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
                            return

                # Join chunks efficiently
                response_text = "".join(response_chunks).strip()
                logger.info(
                    f"✅ Response complete: {len(response_text):,} chars from {chunk_count} chunks"
                )

                if req.low_vram and not req.text_only:
                    logger.info(
                        f"🧹 [Low VRAM Mode] Unloading Ollama model {req.model} to free VRAM"
                    )
                    unload_ollama_model(
                        req.model, OLLAMA_ENDPOINT.replace("/api/chat", "")
                    )
                else:
                    logger.info(
                        f"⚡ [Performance Mode] Keeping Ollama model {req.model} loaded"
                    )

            # ── 7. Process reasoning content if present ─────────────────────────────────────
            reasoning_content = ""
            final_answer = response_text

            logger.info(
                f"🔍 Raw response preview (first 500 chars): {response_text[:500] if len(response_text) > 500 else response_text}"
            )
            logger.info(
                f"🔍 Contains '<think>': {'<think>' in response_text.lower()}, Contains '<thinking>': {'<thinking>' in response_text.lower()}"
            )

            if has_reasoning_content(response_text):
                reasoning_content, final_answer = separate_thinking_from_final_output(
                    response_text
                )
                logger.info(
                    f"🧠 Reasoning model detected - separated {len(reasoning_content)} chars of thinking from {len(final_answer)} chars of answer"
                )
            else:
                logger.info(f"ℹ️ No reasoning tags found in response")

            # ── 8. Text-to-speech (with heartbeats) ─────────────────────────────────────────
            # Moved BEFORE persistence so we can save the audio path
            audio_path = None

            if req.text_only:
                logger.info("🔇 [Text Only Mode] Skipping TTS generation")
            elif not final_answer or not final_answer.strip():
                logger.warning("⚠️ [TTS Skip] No text to speak - final_answer is empty")
            else:
                yield f"data: {json.dumps({'status': 'generating_audio', 'detail': 'Generating voice response...'})}\n\n"

                audio_prompt_path = req.audio_prompt or HARVIS_VOICE_PATH
                if not os.path.isfile(audio_prompt_path):
                    logger.warning(
                        "Audio prompt %s not found, falling back to default voice.",
                        audio_prompt_path,
                    )
                    audio_prompt_path = None

                if audio_prompt_path:
                    if not os.path.exists(audio_prompt_path):
                        logger.warning(
                            f"JARVIS voice prompt missing at: {audio_prompt_path}"
                        )
                    else:
                        logger.info(f"Cloning voice using prompt: {audio_prompt_path}")

                logger.info(
                    f"🎤 TTS: Generating speech for {len(final_answer)} chars: '{final_answer[:80]}...'"
                )

                try:
                    sr, wav = None, None
                    async for event in run_tts_with_heartbeats(
                        text=final_answer,
                        audio_prompt=audio_prompt_path,
                        exaggeration=req.exaggeration,
                        temperature=req.temperature,
                        cfg_weight=req.cfg_weight,
                        auto_unload=req.low_vram,
                    ):
                        if event["type"] == "heartbeat":
                            yield f"data: {json.dumps({'status': 'processing', 'detail': 'Generating audio...'})}\n\n"
                        elif event["type"] == "result":
                            sr, wav = event["data"]

                    if (
                        sr is not None
                        and wav is not None
                        and hasattr(wav, "shape")
                        and len(wav.shape) >= 1
                        and wav.shape[0] > 0
                    ):
                        filename = f"response_{uuid.uuid4()}.wav"
                        filepath = os.path.join(tempfile.gettempdir(), filename)
                        sf.write(filepath, wav, sr)
                        logger.info("Audio written to %s", filepath)
                        audio_path = f"/api/audio/{filename}"
                    else:
                        logger.warning(
                            "⚠️ TTS unavailable - returning response without audio"
                        )
                except Exception as e:
                    logger.error(f"❌ TTS Generation failed: {e}")

            # ── 9. Persist chat history to database ─────────────────────────────────────────
            yield f"data: {json.dumps({'status': 'saving', 'detail': 'Saving to history...'})}\n\n"

            msg_metadata = {}
            if audio_path:
                msg_metadata["audio_path"] = audio_path
                msg_metadata["videos"] = []  # Placeholder

            if session_id:
                try:
                    session = await chat_history_manager.get_session(
                        session_id, current_user.id
                    )
                    if not session:
                        session = await chat_history_manager.create_session(
                            user_id=current_user.id,
                            title="New Chat",
                            model_used=req.model,
                        )
                        session_id = session.id

                    await chat_history_manager.add_message(
                        user_id=current_user.id,
                        session_id=session_id,
                        role="user",
                        content=current_message_content,
                        model_used=req.model,
                        input_type="text",
                    )
                    asst_msg = await chat_history_manager.add_message(
                        user_id=current_user.id,
                        session_id=session_id,
                        role="assistant",
                        content=final_answer,
                        reasoning=reasoning_content if reasoning_content else None,
                        model_used=req.model,
                        input_type="text",
                        metadata=msg_metadata,
                    )
                    message_id = asst_msg.id
                    logger.info(
                        f"💾 Saved chat messages to session {session_id} (msg_id: {message_id})"
                    )
                except Exception as e:
                    logger.error(f"Error saving chat history: {e}")
                    message_id = None
            else:
                try:
                    session = await chat_history_manager.create_session(
                        user_id=current_user.id, title="New Chat", model_used=req.model
                    )
                    session_id = session.id
                    await chat_history_manager.add_message(
                        user_id=current_user.id,
                        session_id=session_id,
                        role="user",
                        content=current_message_content,
                        model_used=req.model,
                        input_type="text",
                    )
                    asst_msg = await chat_history_manager.add_message(
                        user_id=current_user.id,
                        session_id=session_id,
                        role="assistant",
                        content=final_answer,
                        reasoning=reasoning_content if reasoning_content else None,
                        model_used=req.model,
                        input_type="text",
                        metadata=msg_metadata,
                    )
                    message_id = asst_msg.id
                    logger.info(
                        f"💾 Created new session {session_id} and saved messages (msg_id: {message_id})"
                    )
                except Exception as e:
                    logger.error(f"Error creating session and saving history: {e}")
                    session_id = None
                    message_id = None

            new_history = history + [{"role": "assistant", "content": final_answer}]

            # ── 10. Final complete response ─────────────────────────────────────────────────
            response_data = {
                "status": "complete",
                "history": new_history,
                "session_id": str(session_id) if session_id else None,
                "message_id": message_id,
                "final_answer": final_answer,
            }

            if audio_path:
                response_data["audio_path"] = audio_path

            if reasoning_content:
                response_data["reasoning"] = reasoning_content
                logger.info(
                    f"🧠 Returning reasoning content ({len(reasoning_content)} chars)"
                )

            logger.info("✅ Chat streaming response complete")
            yield f"data: {json.dumps(response_data)}\n\n"

        except Exception as e:
            logger.exception("Chat stream error")
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        stream_chat(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Critical for Nginx proxy
        },
    )


@app.post("/api/vision-chat", tags=["vision"])
async def vision_chat(
    req: VisionChatRequest,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
):
    """
    Vision chat endpoint using Ollama VL models (llava, moondream, bakllava, etc.).
    Now uses SSE streaming with heartbeats to prevent browser idle timeouts.
    """
    import asyncio

    async def stream_vision_chat():
        try:
            logger.info(
                f"🖼️ Vision chat - User: {current_user.username}, Model: {req.model}, Images: {len(req.images)}"
            )
            logger.info(
                f"⚙️ Vision mode flags - low_vram: {req.low_vram}, text_only: {req.text_only}"
            )

            yield f"data: {json.dumps({'status': 'starting', 'message': 'Processing vision request...'})}\n\n"

            # Extract base64 data from images and ensure proper format
            yield f"data: {json.dumps({'status': 'processing', 'detail': 'Processing images...'})}\n\n"
            processed_images = []
            saved_image_paths = []  # Track saved image file paths
            for idx, img in enumerate(req.images):
                try:
                    logger.info(
                        f"🖼️ Processing image {idx + 1}/{len(req.images)} - Input length: {len(img)}"
                    )

                    if "," in img:
                        header, data = img.split(",", 1)
                        logger.info(
                            f"🖼️ Image {idx + 1}: Found data URI header: {header[:50]}..."
                        )
                        img_data = data
                    else:
                        logger.info(f"🖼️ Image {idx + 1}: No data URI header found")
                        img_data = img

                    img_data = (
                        img_data.strip()
                        .replace("\n", "")
                        .replace("\r", "")
                        .replace(" ", "")
                    )

                    try:
                        decoded = base64.b64decode(img_data)
                        logger.info(
                            f"🖼️ Image {idx + 1}: Valid base64, decoded size: {len(decoded)} bytes"
                        )

                        if len(decoded) > 8:
                            if decoded[:8] == b"\x89PNG\r\n\x1a\n":
                                logger.info(f"🖼️ Image {idx + 1}: PNG format detected")
                            elif decoded[:2] == b"\xff\xd8":
                                logger.info(f"🖼️ Image {idx + 1}: JPEG format detected")
                            elif decoded[:4] == b"GIF8":
                                logger.info(
                                    f"🖼️ Image {idx + 1}: GIF format detected - Converting to PNG"
                                )
                            elif decoded[:4] == b"RIFF":
                                logger.info(
                                    f"🖼️ Image {idx + 1}: WEBP format detected - Converting to PNG"
                                )
                            else:
                                logger.warning(
                                    f"🖼️ Image {idx + 1}: Unknown format, first bytes: {decoded[:10].hex()} - Attempting conversion"
                                )
                        else:
                            logger.warning(
                                f"🖼️ Image {idx + 1}: Data too short to check magic bytes"
                            )

                        try:
                            image_io = io.BytesIO(decoded)
                            with Image.open(image_io) as pil_img:
                                if pil_img.mode in ("RGBA", "P"):
                                    pil_img = pil_img.convert("RGB")
                                output_io = io.BytesIO()
                                pil_img.save(output_io, format="PNG")
                                decoded = output_io.getvalue()
                                logger.info(
                                    f"🖼️ Image {idx + 1}: Converted to PNG, new size: {len(decoded)} bytes"
                                )
                        except Exception as pil_err:
                            logger.error(
                                f"🖼️ Image {idx + 1}: Pillow conversion failed: {pil_err} - Sending original"
                            )

                        clean_b64 = base64.b64encode(decoded).decode("utf-8")
                        processed_images.append(clean_b64)

                        # Save image to disk for persistence
                        try:
                            image_filename = f"{uuid.uuid4()}.png"
                            image_path = os.path.join(IMAGES_DIR, image_filename)
                            with open(image_path, "wb") as img_file:
                                img_file.write(decoded)
                            saved_image_paths.append(f"/api/images/{image_filename}")
                            logger.info(f"🖼️ Image {idx + 1}: Saved to {image_path}")
                        except Exception as save_err:
                            logger.error(
                                f"🖼️ Image {idx + 1}: Failed to save to disk: {save_err}"
                            )

                    except Exception as decode_err:
                        logger.error(
                            f"🖼️ Image {idx + 1}: Failed to decode base64: {decode_err}"
                        )
                        processed_images.append(img_data)

                except Exception as img_err:
                    logger.error(f"🖼️ Error processing image {idx + 1}: {img_err}")
                    continue

            if not processed_images:
                yield f"data: {json.dumps({'status': 'error', 'error': 'No valid images provided'})}\n\n"
                return

            # Build messages array for Ollama vision
            messages = []
            system_prompt = (
                'You are "Harvis", an AI assistant with vision capabilities. '
                "Analyze the provided image(s) and respond helpfully to the user's question. "
                "Be concise but thorough in your visual analysis."
            )
            messages.append({"role": "system", "content": system_prompt})

            for msg in req.history:
                messages.append({"role": msg["role"], "content": msg["content"]})

            user_message = {
                "role": "user",
                "content": req.message,
                "images": processed_images,
            }
            messages.append(user_message)

            payload = {"model": req.model, "messages": messages, "stream": False}

            logger.info(
                f"🖼️ VISION: Sending to Ollama model '{req.model}' with {len(processed_images)} image(s)"
            )

            # Send to Ollama with heartbeats
            yield f"data: {json.dumps({'status': 'inference', 'detail': f'Analyzing with {req.model}...'})}\n\n"

            ollama_response = None
            async for event in run_ollama_with_heartbeats(
                "/api/chat", payload, timeout=3600
            ):
                if event["type"] == "heartbeat":
                    elapsed = event["elapsed"]
                    yield f"data: {json.dumps({'status': 'heartbeat', 'count': event['count'], 'elapsed': elapsed, 'detail': f'Still analyzing... ({elapsed}s)'})}\n\n"
                elif event["type"] == "result":
                    ollama_response = event["data"]
                    break

            if ollama_response is None:
                yield f"data: {json.dumps({'status': 'error', 'error': 'Ollama vision request failed'})}\n\n"
                return

            if ollama_response.status_code != 200:
                logger.error(
                    f"Ollama vision error {ollama_response.status_code}: {ollama_response.text}"
                )
                yield f"data: {json.dumps({'status': 'error', 'error': f'Ollama vision error: {ollama_response.status_code}'})}\n\n"
                return

            response_text = (
                ollama_response.json().get("message", {}).get("content", "").strip()
            )
            logger.info(f"🖼️ VISION: Got response ({len(response_text)} chars)")

            if req.low_vram:
                logger.info(f"🧹 [Low VRAM Mode] Unloading vision model {req.model}")
                unload_ollama_model(req.model, LOCAL_OLLAMA_URL)

            # Separate reasoning if present
            reasoning_content = None
            final_answer = response_text

            import re

            think_pattern = r"<think>([\s\S]*?)</think>"
            think_matches = re.findall(think_pattern, response_text, re.IGNORECASE)
            if think_matches:
                reasoning_content = "\n\n".join(think_matches).strip()
                final_answer = re.sub(
                    think_pattern, "", response_text, flags=re.IGNORECASE
                ).strip()

            # ── Persist chat history to database ──────────────────────────────────────────
            yield f"data: {json.dumps({'status': 'saving', 'detail': 'Saving to history...'})}\n\n"
            session_id = req.session_id
            logger.info(
                f"🖼️ VISION: Session persistence starting - received session_id: {session_id}"
            )
            try:
                from uuid import UUID

                if session_id:
                    logger.info(f"🖼️ VISION: Using existing session_id: {session_id}")
                    session = await chat_history_manager.get_session(
                        session_id, current_user.id
                    )
                    if not session:
                        logger.info(f"🖼️ VISION: Session not found, creating new one")
                        session = await chat_history_manager.create_session(
                            user_id=current_user.id,
                            title="Vision Chat",
                            model_used=req.model,
                        )
                        session_id = str(session.id)
                else:
                    logger.info(
                        f"🖼️ VISION: No session_id provided, creating new session"
                    )
                    session = await chat_history_manager.create_session(
                        user_id=current_user.id,
                        title="Vision Chat",
                        model_used=req.model,
                    )
                    session_id = str(session.id)
                    logger.info(f"🖼️ VISION: Created new session: {session_id}")

                user_content = req.message or "What do you see in this image?"

                # Build metadata with image paths if images were saved
                metadata = {}
                if saved_image_paths:
                    metadata["images"] = saved_image_paths
                    metadata["image_count"] = len(saved_image_paths)

                await chat_history_manager.add_message(
                    user_id=current_user.id,
                    session_id=session_id,
                    role="user",
                    content=user_content,
                    model_used=req.model,
                    input_type="screen",
                    metadata=metadata,
                )
                await chat_history_manager.add_message(
                    user_id=current_user.id,
                    session_id=session_id,
                    role="assistant",
                    content=final_answer,
                    reasoning=reasoning_content if reasoning_content else None,
                    model_used=req.model,
                    input_type="text",
                )
                logger.info(f"💾 Vision chat: Saved messages to session {session_id}")
            except Exception as e:
                logger.error(f"Error saving vision chat history: {e}")

            # Generate TTS if not text-only mode
            audio_path = None
            if not req.text_only:
                if not final_answer or not final_answer.strip():
                    logger.warning(
                        "⚠️ VISION: [TTS Skip] No text to speak - final_answer is empty"
                    )
                else:
                    yield f"data: {json.dumps({'status': 'generating_audio', 'detail': 'Generating voice response...'})}\n\n"
                    logger.info(
                        f"🎤 VISION TTS: Generating speech for {len(final_answer)} chars: '{final_answer[:80]}...'"
                    )
                    try:
                        sr, wav = None, None
                        async for event in run_tts_with_heartbeats(
                            text=final_answer,
                            audio_prompt=HARVIS_VOICE_PATH,
                            exaggeration=0.5,
                            temperature=0.5,
                            cfg_weight=2.0,
                            auto_unload=req.low_vram,
                        ):
                            if event["type"] == "heartbeat":
                                yield f"data: {json.dumps({'status': 'processing', 'detail': 'Generating audio...'})}\n\n"
                            elif event["type"] == "result":
                                sr, wav = event["data"]

                        if wav is not None:
                            filename = f"vision_{uuid.uuid4()}.wav"
                            filepath = os.path.join(tempfile.gettempdir(), filename)
                            sf.write(filepath, wav, sr)
                            audio_path = f"/api/audio/{filename}"
                            logger.info(f"🔊 VISION: Generated TTS audio: {audio_path}")
                    except Exception as tts_error:
                        logger.error(
                            f"TTS generation failed for vision response: {tts_error}"
                        )

            # Final complete response
            response_data = {
                "status": "complete",
                "response": final_answer,
                "final_answer": final_answer,
                "model": req.model,
                "images_processed": len(processed_images),
                "session_id": session_id,
            }

            if reasoning_content:
                response_data["reasoning"] = reasoning_content

            if audio_path:
                response_data["audio_path"] = audio_path

            logger.info("✅ Vision chat streaming response complete")
            yield f"data: {json.dumps(response_data)}\n\n"

        except Exception as e:
            logger.exception("Vision chat stream error")
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        stream_vision_chat(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Critical for Nginx proxy
        },
    )


@app.get("/api/audio/{filename}", tags=["audio"])
async def serve_audio(filename: str):
    """
    FastAPI static audio fallback (use nginx /audio alias in production for speed).
    """
    full_path = os.path.join(tempfile.gettempdir(), filename)
    if not os.path.exists(full_path):
        raise HTTPException(404, f"Audio file not found: {filename}")
    return FileResponse(full_path, media_type="audio/wav")


@app.get("/api/images/{filename}", tags=["images"])
async def serve_image(
    filename: str, current_user: UserResponse = Depends(get_current_user)
):
    """
    Serve chat images from persistent storage. Requires authentication.
    """
    full_path = os.path.join(IMAGES_DIR, filename)
    if not os.path.exists(full_path):
        raise HTTPException(404, f"Image file not found: {filename}")
    return FileResponse(full_path, media_type="image/png")


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
        os.remove(temp_image_path)  # Clean up temp file

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
    global \
        _last_vision_request_time, \
        _vision_endpoint_enabled, \
        _vision_request_count, \
        _vision_error_count

    # Circuit breaker: Check if endpoint is disabled
    if not _vision_endpoint_enabled:
        logger.warning("🚫 Vision endpoint is disabled due to repeated issues")
        raise HTTPException(
            status_code=503, detail="Vision analysis temporarily disabled"
        )

    # Circuit breaker: Check error rate
    if _vision_request_count > 10 and _vision_error_count / _vision_request_count > 0.8:
        logger.error("🚫 Circuit breaker activated: too many failures")
        _vision_endpoint_enabled = False
        raise HTTPException(
            status_code=503, detail="Vision analysis disabled due to high error rate"
        )

    _vision_request_count += 1
    logger.info(
        f"📊 Vision request #{_vision_request_count} (errors: {_vision_error_count})"
    )

    # Rate limiting: only allow one vision request at a time
    async with _vision_processing_lock:
        current_time = time.time()

        # Enforce minimum 2 second delay between requests
        time_since_last = current_time - _last_vision_request_time
        if time_since_last < 2.0:
            wait_time = 2.0 - time_since_last
            logger.info(
                f"⏳ Rate limiting: waiting {wait_time:.1f}s before processing vision request"
            )
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
                raise HTTPException(
                    status_code=500, detail=f"Screen analysis failed: {str(e)}"
                )
            finally:
                # Always clean up temp file, even if analysis fails
                if temp_image_path and os.path.exists(temp_image_path):
                    try:
                        os.remove(temp_image_path)
                        temp_image_path = None
                    except OSError as e:
                        logger.warning(
                            f"Failed to remove temp file {temp_image_path}: {e}"
                        )

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
            system_prompt = (
                req.system_prompt
                or "You are Harvis AI, an AI assistant analyzing what the user is seeing on their screen. Provide helpful insights, suggestions, or commentary about what you observe. Be conversational and helpful."
            )

            logger.info(f"🤖 Generating response with {req.model}")
            if req.model == "gemini-1.5-flash":
                # Use Gemini for response
                try:
                    llm_response = query_gemini(
                        f"Screen analysis: {qwen_analysis}\n\nPlease provide helpful insights about this screen.",
                        [],
                    )
                except Exception as e:
                    logger.error(f"Gemini response failed: {e}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"AI response generation failed: {str(e)}",
                    )
            else:
                # Use Ollama for response
                payload = {
                    "model": req.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": f"Screen analysis: {qwen_analysis}\n\nPlease provide helpful insights about this screen.",
                        },
                    ],
                    "stream": False,
                }

                logger.info(f"→ Asking Ollama with model {req.model}")
                headers = (
                    {"Authorization": f"Bearer {API_KEY}"} if API_KEY != "key" else {}
                )

                try:
                    resp = requests.post(
                        f"{OLLAMA_URL}/api/chat",
                        json=payload,
                        headers=headers,
                        timeout=90,
                    )

                    if resp.status_code != 200:
                        logger.error("Ollama error %s: %s", resp.status_code, resp.text)
                        raise HTTPException(
                            status_code=500,
                            detail=f"LLM request failed with status {resp.status_code}",
                        )

                    llm_response = (
                        resp.json().get("message", {}).get("content", "").strip()
                    )

                    if not llm_response:
                        logger.warning("Empty response from Ollama")
                        llm_response = "I was able to analyze the screen but couldn't generate a detailed response. Please try again."

                except requests.RequestException as e:
                    logger.error(f"Ollama request failed: {e}")
                    raise HTTPException(
                        status_code=500, detail=f"AI service unavailable: {str(e)}"
                    )

            # Reload TTS/Whisper models for future use
            logger.info(
                "🔄 Reloading TTS/Whisper models after enhanced screen analysis"
            )
            reload_models_if_needed()

            logger.info("✅ Enhanced screen analysis complete - all models restored")
            return {
                "response": llm_response,
                "screen_analysis": qwen_analysis,
                "model_used": req.model,
            }

        except HTTPException:
            # Re-raise HTTP exceptions without wrapping
            _vision_error_count += 1
            raise
        except Exception as e:
            _vision_error_count += 1
            logger.error(
                f"Analyze and respond failed with unexpected error: {e}", exc_info=True
            )
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
            "status": "enabled" if _vision_endpoint_enabled else "disabled",
        }


@app.post("/api/analyze-screen-with-tts", tags=["vision"])
async def analyze_screen_with_tts(req: ScreenAnalysisWithTTSRequest):
    """
    Complete screen analysis with Qwen2VL + LLM response + TTS audio output.
    Implements intelligent model management: Qwen2VL -> LLM -> TTS pipeline.
    """
    try:
        # Phase 1: Unload ALL models for maximum memory for Qwen2VL processing
        logger.info(
            "🖼️ Phase 1: Starting screen analysis - clearing ALL GPU memory for Qwen2VL"
        )
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
        system_prompt = (
            req.system_prompt
            or "You are Harvis AI, an AI assistant. Based on the screen analysis, provide helpful, conversational insights. Keep responses under 100 words for voice output."
        )

        if req.model == "gemini-1.5-flash":
            llm_response = query_gemini(
                f"Screen analysis: {qwen_analysis}\n\nProvide helpful insights about this screen.",
                [],
            )
        else:
            payload = {
                "model": req.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"Screen analysis: {qwen_analysis}\n\nProvide helpful insights about this screen.",
                    },
                ],
                "stream": False,
            }
            headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY != "key" else {}
            resp = requests.post(
                f"{OLLAMA_URL}/api/chat", json=payload, headers=headers, timeout=90
            )
            resp.raise_for_status()
            llm_response = resp.json().get("message", {}).get("content", "").strip()

        # Phase 3: Reload TTS for audio generation
        logger.info("🔊 Phase 3: Reloading TTS for audio generation")
        reload_models_if_needed()

        # Generate TTS audio
        audio_prompt_path = req.audio_prompt or HARVIS_VOICE_PATH
        if not os.path.isfile(audio_prompt_path):
            logger.warning(
                f"Audio prompt {audio_prompt_path} not found, using default voice"
            )
            audio_prompt_path = None

        sr, wav = safe_generate_speech_optimized(
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
                "tts_generation": "✅ Completed",
            },
        }

    except Exception as e:
        logger.error("Screen analysis with TTS failed: %s", e)
        # Ensure models are reloaded on error
        reload_models_if_needed()
        raise HTTPException(500, str(e)) from e


# Whisper model will be loaded on demand


@app.post("/api/mic-chat", tags=["voice"])
async def mic_chat(
    file: UploadFile = File(...),
    model: str = Form(DEFAULT_MODEL),
    session_id: Optional[str] = Form(None),
    research_mode: str = Form("false"),
    low_vram: bool = Form(True),
    text_only: bool = Form(False),
    current_user: UserResponse = Depends(get_current_user),
):
    """
    Voice chat endpoint - transcribes audio and generates AI response with TTS.
    Returns JSON response (not SSE streaming) for simpler frontend handling.
    """
    tmp_path = None

    try:
        # ── 1. Read and save audio file ──────────────────────────────────────────────
        contents = await file.read()
        if len(contents) == 0:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "error": "No audio data received"},
            )

        header = contents[:4]
        if header == b"RIFF":
            file_ext = ".wav"
        elif header == b"OggS":
            file_ext = ".ogg"
        elif header.startswith(b"ID3") or header.startswith(b"\xff\xfb"):
            file_ext = ".mp3"
        elif header.startswith(b"\x1a\x45\xdf\xa3"):
            file_ext = ".webm"
        else:
            if file.filename:
                _, file_ext = os.path.splitext(file.filename)
                if not file_ext:
                    file_ext = ".wav"
            else:
                file_ext = ".wav"

        tmp_id = str(uuid.uuid4())
        tmp_path = os.path.join(tempfile.gettempdir(), f"{tmp_id}{file_ext}")
        with open(tmp_path, "wb") as f:
            f.write(contents)

        logger.info(f"🎤 MIC-CHAT: File saved to {tmp_path} ({len(contents)} bytes)")

        is_research_mode = research_mode.lower() == "true"

        # ── 2. Transcribe audio ──────────────────────────────────────────────────────
        try:
            transcription_result = {}
            async for event in run_stt_with_heartbeats(tmp_path):
                if event["type"] == "result":
                    transcription_result = event["data"]

            text = transcription_result.get("text", "").strip()
            logger.info(f"🎤 Transcription complete: {text[:100]}...")
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return JSONResponse(
                status_code=500,
                content={"status": "error", "error": f"Transcription failed: {str(e)}"},
            )

        if not text:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "error": "Could not transcribe any speech from audio",
                },
            )

        # ── 3. Load session history (like /api/chat) ─────────────────────────────────
        history = []
        if session_id:
            try:
                from uuid import UUID

                session_uuid = UUID(session_id)
                recent_messages = await chat_history_manager.get_recent_messages(
                    session_id=session_uuid, user_id=current_user.id, limit=10
                )
                history = chat_history_manager.format_messages_for_context(
                    recent_messages
                )
                logger.info(
                    f"🎤 MIC-CHAT: Using session {session_id} with {len(recent_messages)} recent messages"
                )
            except (ValueError, Exception) as e:
                logger.error(f"Invalid session_id or error loading context: {e}")
                history = []

        history = history + [{"role": "user", "content": text}]

        # ── 4. Generate AI response ─────────────────────────────────────────────────
        response_text = ""
        reasoning_content = ""
        final_answer = ""

        try:
            if is_research_mode:
                logger.info(
                    f"🔬 MIC-CHAT: Research mode enabled for query: {text[:50]}..."
                )
                research_result = await run_in_threadpool(
                    research_agent, text, model, use_advanced=False
                )

                if "error" in research_result:
                    response_text = f"Research Error: {research_result['error']}"
                else:
                    analysis = research_result.get("analysis", "No analysis available")
                    sources = research_result.get("sources", [])
                    response_text = analysis
                    if sources:
                        response_text += "\n\n**Sources:**\n" + "\n".join(
                            [f"- {s.get('title', 'Link')}" for s in sources[:3]]
                        )
            else:
                if model == "gemini-1.5-flash":
                    response_text = query_gemini(text, history[:-1])
                else:
                    sys_prompt_path = os.path.join(
                        os.path.dirname(__file__), "system_prompt.txt"
                    )
                    try:
                        with open(sys_prompt_path, "r", encoding="utf-8") as f:
                            sys_prompt = f.read().strip()
                    except FileNotFoundError:
                        sys_prompt = (
                            'You are "Jarves", a voice-first local assistant. '
                            "Reply in ≤25 spoken-style words, sprinkling brief Spanish when natural."
                        )

                    messages = [{"role": "system", "content": sys_prompt}]
                    for msg in history[:-1]:
                        messages.append(
                            {"role": msg["role"], "content": msg["content"]}
                        )
                    messages.append({"role": "user", "content": text})

                    logger.info(
                        f"🎤 MIC-CHAT: Sending {len(messages)} messages to Ollama (including {len(history) - 1} context messages)"
                    )

                    payload = {
                        "model": model,
                        "messages": messages,
                        "stream": False,
                    }

                    ollama_response = None
                    async for event in run_ollama_with_heartbeats(
                        "/api/chat", payload, timeout=3600
                    ):
                        if event["type"] == "result":
                            ollama_response = event["data"]
                            break

                    if ollama_response is None:
                        return JSONResponse(
                            status_code=500,
                            content={
                                "status": "error",
                                "error": "Ollama request failed",
                            },
                        )

                    if ollama_response.status_code != 200:
                        return JSONResponse(
                            status_code=500,
                            content={
                                "status": "error",
                                "error": f"Ollama error: {ollama_response.status_code}",
                            },
                        )

                    response_text = (
                        ollama_response.json()
                        .get("message", {})
                        .get("content", "")
                        .strip()
                    )

                    if low_vram and not text_only:
                        logger.info(
                            f"🧹 [Low VRAM Mode] Unloading Ollama model {model} to free VRAM for TTS"
                        )
                        unload_ollama_model(model, "")

                if has_reasoning_content(response_text):
                    reasoning_content, final_answer = (
                        separate_thinking_from_final_output(response_text)
                    )
                    logger.info(
                        f"🧠 MIC-CHAT: Separated {len(reasoning_content)} chars reasoning from {len(final_answer)} chars answer"
                    )
                else:
                    final_answer = response_text

        except Exception as e:
            logger.error(f"MIC-CHAT: AI generation failed: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "error": f"AI response generation failed: {str(e)}",
                },
            )

        # ── 5. Generate TTS ──────────────────────────────────────────────────────────
        audio_path = None

        if text_only:
            logger.info("🔇 MIC-CHAT: [Text Only Mode] Skipping TTS generation")
        elif not final_answer or not final_answer.strip():
            logger.warning(
                "⚠️ MIC-CHAT: [TTS Skip] No text to speak - final_answer is empty"
            )
        else:
            try:
                audio_prompt_path = (
                    HARVIS_VOICE_PATH if os.path.isfile(HARVIS_VOICE_PATH) else None
                )
                if audio_prompt_path:
                    logger.info(
                        f"🎤 MIC-CHAT: Cloning voice using prompt: {audio_prompt_path}"
                    )

                logger.info(
                    f"🎤 MIC-CHAT TTS: Generating speech for {len(final_answer)} chars: '{final_answer[:80]}...'"
                )

                sr, wav = await run_in_threadpool(
                    safe_generate_speech_optimized,
                    text=final_answer,
                    exaggeration=0.5,
                    temperature=0.6,
                    cfg_weight=2.5,
                    audio_prompt=audio_prompt_path,
                    auto_unload=low_vram,
                )

                if (
                    sr is not None
                    and wav is not None
                    and hasattr(wav, "shape")
                    and len(wav.shape) >= 1
                    and wav.shape[0] > 0
                ):
                    fname = f"response_{uuid.uuid4()}.wav"
                    filepath = os.path.join(tempfile.gettempdir(), fname)
                    sf.write(filepath, wav, sr)
                    audio_path = f"/api/audio/{fname}"
                    logger.info(f"🔊 MIC-CHAT: Audio written to {filepath}")
                else:
                    logger.warning("⚠️ MIC-CHAT: TTS returned no audio")
            except Exception as e:
                logger.error(f"❌ MIC-CHAT: TTS failed: {e}")

        # ── 6. Save to database ──────────────────────────────────────────────────────
        message_id = None
        try:
            # Handle session creation if needed
            saved_session_id = session_id
            if not saved_session_id:
                session = await chat_history_manager.create_session(
                    user_id=current_user.id, title="Voice Chat", model_used=model
                )
                saved_session_id = str(session.id)
                logger.info(f"🆕 MIC-CHAT: Created new session {saved_session_id}")
            else:
                # Verify session exists
                session = await chat_history_manager.get_session(
                    saved_session_id, current_user.id
                )
                if not session:
                    session = await chat_history_manager.create_session(
                        user_id=current_user.id,
                        title="Voice Chat",
                        model_used=model,
                    )
                    saved_session_id = str(session.id)
            session_id = saved_session_id

            await chat_history_manager.add_message(
                user_id=current_user.id,
                session_id=session_id,
                role="user",
                content=text,
                model_used=model,
                input_type="voice",
            )

            # Metadata for assistant message
            msg_metadata = {}
            if audio_path:
                msg_metadata["audio_path"] = audio_path

            asst_msg = await chat_history_manager.add_message(
                user_id=current_user.id,
                session_id=session_id,
                role="assistant",
                content=final_answer,
                reasoning=reasoning_content if reasoning_content else None,
                model_used=model,
                input_type="voice",
                metadata=msg_metadata,
            )
            message_id = asst_msg.id
            logger.info(
                f"💾 MIC-CHAT: Saved messages to session {session_id} (msg_id: {message_id})"
            )
        except Exception as e:
            logger.error(f"MIC-CHAT: Error saving chat history: {e}")

        # ── 7. Final complete response ────────────────────────────────────────────────
        new_history = history + [{"role": "assistant", "content": final_answer}]

        response_data = {
            "status": "complete",
            "history": new_history,
            "session_id": str(session_id) if session_id else None,
            "message_id": message_id,
            "final_answer": final_answer,
            "transcription": text,
        }

        if audio_path:
            response_data["audio_path"] = audio_path

        if reasoning_content:
            response_data["reasoning"] = reasoning_content

        logger.info(
            f"✅ MIC-CHAT: Complete - transcribed '{text[:50]}...', response '{final_answer[:50]}...'"
        )

        return JSONResponse(content=response_data)

    except Exception as e:
        logger.exception("MIC-CHAT error")
        return JSONResponse(
            status_code=500, content={"status": "error", "error": str(e)}
        )
    finally:
        # Cleanup temp file
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except:
                pass



# Research endpoints using the enhanced research module with advanced pipeline
from agent_research import research_agent, fact_check_agent, comparative_research_agent
from agent_research import (
    async_research_agent,
    async_fact_check_agent,
    async_comparative_research_agent,
)
from agent_research import get_research_agent_stats, get_mcp_tool
from research.web_search import WebSearchAgent
from pydantic import Field
from typing import Optional, List


class AdvancedResearchRequest(BaseModel):
    """Enhanced research request with advanced options"""

    message: str
    model: str = "mistral"
    history: List[Dict[str, str]] = []
    session_id: Optional[str] = None  # Chat session ID for history persistence
    use_advanced: bool = Field(
        default=False, description="Use advanced research pipeline"
    )
    enable_streaming: bool = Field(
        default=False, description="Enable streaming progress"
    )
    enable_verification: bool = Field(
        default=True, description="Enable response verification"
    )


@app.post("/api/research-chat", tags=["research"])
async def research_chat(
    req: Union[ResearchChatRequest, AdvancedResearchRequest],
    current_user: UserResponse = Depends(get_current_user),
):
    """
    Enhanced research chat endpoint with SSE streaming to prevent Nginx 499 timeouts.
    Streams progress updates during web searches and LLM inference.
    """

    async def stream_research():
        try:
            if not req.message:
                yield f"data: {json.dumps({'status': 'error', 'error': 'Message is required'})}\n\n"
                return

            # 1. Initial status
            yield f"data: {json.dumps({'status': 'starting', 'message': req.message})}\n\n"

            use_advanced = getattr(req, "use_advanced", False)

            # 2. Unload models
            yield f"data: {json.dumps({'status': 'preparing', 'detail': 'Freeing GPU memory'})}\n\n"
            unload_models()

            # 3. Web search phase
            yield f"data: {json.dumps({'status': 'searching', 'detail': 'Searching the web...'})}\n\n"

            response_content = ""
            sources = []
            sources_found = 0
            videos = []  # YouTube videos for Perplexity-style display

            try:
                if use_advanced:
                    # Advanced research
                    yield f"data: {json.dumps({'status': 'researching', 'detail': 'Running advanced research pipeline'})}\n\n"
                    response_data = await async_research_agent(
                        query=req.message,
                        model=req.model,
                        enable_streaming=False,  # We handle streaming at this level
                    )
                    response_content = (
                        response_data
                        if isinstance(response_data, str)
                        else str(response_data)
                    )
                    sources_found = "embedded"
                    # Try to get videos from advanced research if available
                    if isinstance(response_data, dict):
                        videos = response_data.get("videos", [])
                else:
                    # Standard research
                    yield f"data: {json.dumps({'status': 'researching', 'detail': 'Analyzing search results'})}\n\n"
                    response_data = await run_in_threadpool(
                        research_agent, req.message, req.model, use_advanced=False
                    )

                    if "error" in response_data:
                        response_content = f"Research Error: {response_data['error']}"
                    else:
                        analysis = response_data.get(
                            "analysis", "No analysis available"
                        )
                        sources = response_data.get("sources", [])
                        sources_found = response_data.get("sources_found", 0)
                        videos = response_data.get("videos", [])  # Get YouTube videos

                        response_content = f"{analysis}\n\n"
                        if sources:
                            response_content += (
                                f"**Sources ({sources_found} found):**\n"
                            )
                            for i, source in enumerate(sources[:5], 1):
                                title = source.get("title", "Unknown Title")
                                url = source.get("url", "No URL")
                                response_content += f"{i}. [{title}]({url})\n"

            except Exception as e:
                logger.error(f"Research failed: {e}")
                yield f"data: {json.dumps({'status': 'error', 'error': f'Research failed: {str(e)}'})}\n\n"
                return

            # 4. Process reasoning
            yield f"data: {json.dumps({'status': 'processing', 'detail': 'Formatting response'})}\n\n"

            research_reasoning = ""
            final_research_answer = response_content

            if has_reasoning_content(response_content):
                research_reasoning, final_research_answer = (
                    separate_thinking_from_final_output(response_content)
                )
                logger.info("🧠 Research reasoning model detected")

            # 5. Build history
            new_history = req.history + [
                {"role": "assistant", "content": final_research_answer}
            ]

            # 6. Save messages to chat history
            session_id = getattr(req, "session_id", None)
            saved_session_id = None
            try:
                if session_id:
                    from uuid import UUID

                    session_uuid = UUID(session_id)
                    session = await chat_history_manager.get_session(
                        session_uuid, current_user.id
                    )
                    if not session:
                        session = await chat_history_manager.create_session(
                            user_id=current_user.id,
                            title="Research Chat",
                            model_used=req.model,
                        )
                        saved_session_id = str(session.id)
                    else:
                        saved_session_id = session_id
                else:
                    session = await chat_history_manager.create_session(
                        user_id=current_user.id,
                        title="Research Chat",
                        model_used=req.model,
                    )
                    saved_session_id = str(session.id)

                # Save user message
                await chat_history_manager.add_message(
                    user_id=current_user.id,
                    session_id=UUID(saved_session_id),
                    role="user",
                    content=req.message,
                    model_used=req.model,
                    input_type="text",
                )

                # Save assistant message with sources and videos in metadata
                research_metadata = {
                    "sources": sources[:5] if sources else [],
                    "videos": videos[:6] if videos else [],
                    "sources_found": sources_found,
                }
                await chat_history_manager.add_message(
                    user_id=current_user.id,
                    session_id=UUID(saved_session_id),
                    role="assistant",
                    content=final_research_answer,
                    reasoning=research_reasoning if research_reasoning else None,
                    model_used=req.model,
                    input_type="text",
                    metadata=research_metadata,
                )
                logger.info(
                    f"💾 Saved research chat messages to session {saved_session_id}"
                )
            except Exception as e:
                logger.error(f"Failed to save research chat history: {e}")

            # 7. Complete - send final result
            result_payload = {
                "status": "complete",
                "history": new_history,
                "response": final_research_answer,
                "final_answer": final_research_answer,
                "sources": sources[:5] if sources else [],
                "sources_found": sources_found,
                "videos": videos[:6]
                if videos
                else [],  # Include YouTube videos (max 6)
                "session_id": saved_session_id,  # Return session ID so frontend can track it
            }

            if research_reasoning:
                result_payload["reasoning"] = research_reasoning

            logger.info("✅ Research streaming response complete")
            yield f"data: {json.dumps(result_payload)}\n\n"

        except Exception as e:
            logger.exception("Research stream error")
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        stream_research(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Critical for Nginx
        },
    )


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
        logger.info(
            f"Web search request: query='{req.query}', max_results={req.max_results}, extract_content={req.extract_content}"
        )

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
                "extracted_content": [],
            }

        logger.info(
            f"Search completed: found {len(result.get('search_results', []))} results"
        )
        return result
    except Exception as e:
        logger.exception(
            f"Web search endpoint crashed for query '{req.query}': {str(e)}"
        )
        raise HTTPException(500, f"Search failed: {str(e)}")


# ─── Warmup ────────────────────────────────────────────────────────
# Models will be loaded on demand to manage GPU memory efficiently
logger.info("Models will be loaded on demand for optimal memory management")


# ─── Dev entry-point -----------------------------------------------------------
@app.get("/api/ollama-models", tags=["models"])
async def get_ollama_models():
    """
    Fetches the list of available models from both local and external Ollama servers.
    """
    ollama_model_names = []

    # Fetch from local Ollama
    try:
        url = f"{OLLAMA_URL}/api/tags"
        headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY != "key" else {}
        logger.info(f"Trying to connect to local Ollama at: {url}")
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            models = response.json().get("models", [])
            local_models = [model["name"] for model in models]
            ollama_model_names.extend(local_models)
            logger.info(f"Available models from local Ollama: {local_models}")
        else:
            logger.warning(f"Local Ollama returned status {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"Could not connect to local Ollama: {e}")

    # Fetch from external Ollama (if configured)
    if EXTERNAL_OLLAMA_URL and EXTERNAL_OLLAMA_API_KEY:
        try:
            ext_url = f"{EXTERNAL_OLLAMA_URL}/api/tags"
            ext_headers = {
                "Authorization": f"Bearer {EXTERNAL_OLLAMA_API_KEY}",
                "ngrok-skip-browser-warning": "true",
                "User-Agent": "Harvis-Backend",
            }
            logger.info(f"Trying to connect to external Ollama at: {ext_url}")
            ext_response = requests.get(ext_url, headers=ext_headers, timeout=15)

            if ext_response.status_code == 200:
                try:
                    ext_models = ext_response.json().get("models", [])
                except Exception as json_err:
                    logger.error(
                        f"Failed to parse JSON from external Ollama. Response content: {ext_response.text[:500]}"
                    )
                    ext_models = []

                external_model_names = [model["name"] for model in ext_models]

                # Update the global cache for routing
                global EXTERNAL_MODELS_CACHE

                # We update the set with found models
                for name in external_model_names:
                    EXTERNAL_MODELS_CACHE.add(name)

                # Add external models that aren't already in the list
                for model_name in external_model_names:
                    if model_name not in ollama_model_names:
                        ollama_model_names.append(model_name)
                logger.info(
                    f"Available models from external Ollama: {external_model_names}"
                )
                logger.info(f"Updated EXTERNAL_MODELS_CACHE: {EXTERNAL_MODELS_CACHE}")
            else:
                logger.warning(
                    f"External Ollama returned status {ext_response.status_code}. Content: {ext_response.text[:200]}"
                )
        except requests.exceptions.RequestException as e:
            logger.warning(f"Could not connect to external Ollama: {e}")
            # Do NOT fallback to hardcoded list since we want dynamic discovery only

    # Add Gemini if configured
    if is_gemini_configured():
        ollama_model_names.insert(0, "gemini-1.5-flash")

    if not ollama_model_names:
        raise HTTPException(
            status_code=503, detail="Could not connect to any Ollama server"
        )

    return ollama_model_names


# Vibe command endpoint moved to vibecoding.commands

# Vibe websocket endpoint moved to vibecoding.commands

# ─── Model Management API Endpoints ────────────────────────────────────────────


class MemoryStatsResponse(BaseModel):
    available: bool
    allocated_gb: Optional[float] = None
    reserved_gb: Optional[float] = None
    total_gb: Optional[float] = None
    free_gb: Optional[float] = None
    usage_percent: Optional[float] = None
    device_name: Optional[str] = None
    device_count: Optional[int] = None
    message: Optional[str] = None


class MemoryPressureResponse(BaseModel):
    pressure_level: str
    usage_percent: Optional[float] = None
    free_gb: Optional[float] = None
    allocated_gb: Optional[float] = None
    total_gb: Optional[float] = None
    recommendations: List[str]
    auto_cleanup_suggested: bool


class ModelStatusResponse(BaseModel):
    tts_loaded: bool
    whisper_loaded: bool
    qwen_loaded: bool
    total_models_loaded: int


class UnloadModelRequest(BaseModel):
    model_type: str  # "tts", "whisper", "qwen", "all", "ollama"
    model_name: Optional[str] = None  # For Ollama model unloading


@app.get(
    "/api/models/memory-stats",
    response_model=MemoryStatsResponse,
    tags=["model-management"],
)
async def get_memory_stats():
    """Get detailed GPU memory statistics"""
    from model_manager import get_gpu_memory_stats

    stats = get_gpu_memory_stats()
    return MemoryStatsResponse(**stats)


@app.get(
    "/api/models/memory-pressure",
    response_model=MemoryPressureResponse,
    tags=["model-management"],
)
async def get_memory_pressure():
    """Check memory pressure and get recommendations"""
    from model_manager import check_memory_pressure

    pressure = check_memory_pressure()
    return MemoryPressureResponse(**pressure)


@app.post("/api/models/auto-cleanup", tags=["model-management"])
async def trigger_auto_cleanup():
    """Manually trigger automatic model cleanup"""
    from model_manager import auto_cleanup_if_needed

    cleanup_performed = auto_cleanup_if_needed(
        threshold_percent=50
    )  # Lower threshold for manual trigger

    if cleanup_performed:
        return {
            "message": "Automatic cleanup performed successfully",
            "cleanup_performed": True,
        }
    else:
        return {
            "message": "No cleanup needed - memory usage is healthy",
            "cleanup_performed": False,
        }


@app.get(
    "/api/models/status", response_model=ModelStatusResponse, tags=["model-management"]
)
async def get_model_status():
    """Get current status of all loaded models"""
    from model_manager import tts_model, whisper_model
    from vison_models.llm_connector import qwen_model

    tts_loaded = tts_model is not None
    whisper_loaded = whisper_model is not None
    qwen_loaded = qwen_model is not None

    total_loaded = sum([tts_loaded, whisper_loaded, qwen_loaded])

    return ModelStatusResponse(
        tts_loaded=tts_loaded,
        whisper_loaded=whisper_loaded,
        qwen_loaded=qwen_loaded,
        total_models_loaded=total_loaded,
    )


@app.post("/api/models/unload", tags=["model-management"])
async def unload_model(request: UnloadModelRequest):
    """Unload specific models to free memory"""
    from model_manager import unload_tts_model, unload_whisper_model, unload_models

    unloaded_models = []

    if request.model_type == "all":
        # Unload all models
        unload_models()
        unload_qwen_model()
        unloaded_models = ["TTS", "Whisper", "Qwen2VL"]

        # Also try to unload Ollama models if model_name provided
        if request.model_name:
            success = unload_ollama_model(request.model_name)
            if success:
                unloaded_models.append(f"Ollama-{request.model_name}")

    elif request.model_type == "tts":
        unload_tts_model()
        unloaded_models.append("TTS")

    elif request.model_type == "whisper":
        unload_whisper_model()
        unloaded_models.append("Whisper")

    elif request.model_type == "qwen":
        unload_qwen_model()
        unloaded_models.append("Qwen2VL")

    elif request.model_type == "ollama":
        if not request.model_name:
            raise HTTPException(400, "model_name required for Ollama model unloading")

        success = unload_ollama_model(request.model_name)
        if success:
            unloaded_models.append(f"Ollama-{request.model_name}")
        else:
            raise HTTPException(
                500, f"Failed to unload Ollama model: {request.model_name}"
            )

    else:
        raise HTTPException(400, f"Invalid model_type: {request.model_type}")

    return {
        "message": f"Successfully unloaded models: {', '.join(unloaded_models)}",
        "unloaded_models": unloaded_models,
    }


@app.post("/api/models/reload", tags=["model-management"])
async def reload_models():
    """Reload models if they were unloaded"""
    from model_manager import reload_models_if_needed

    reload_models_if_needed()

    return {"message": "Models reloaded successfully"}


# ─── User Ollama Settings ──────────────────────────────────────────────────────
# Ollama settings are now managed via Next.js API routes and stored in database
# Python backend queries database directly when needed for Ollama requests


async def get_user_ollama_settings_from_db(user_id: int) -> dict:
    """
    Get user's Ollama settings from database.
    Returns dict with cloud_url, local_url, api_key, preferred_endpoint
    Falls back to global env vars if no user settings found.
    """
    try:
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow(
                """
                SELECT cloud_url, local_url, api_key_encrypted, preferred_endpoint
                FROM user_ollama_settings
                WHERE user_id = $1
                """,
                user_id,
            )

            if result:
                # Decrypt API key if present
                from cryptography.fernet import Fernet
                import base64

                api_key = ""
                if result["api_key_encrypted"]:
                    try:
                        # Use same encryption key as Next.js (from env)
                        # For now, we'll pass encrypted key and decrypt on Next.js side
                        # In production, implement proper key derivation
                        api_key = result[
                            "api_key_encrypted"
                        ]  # Will need proper decryption
                    except Exception as e:
                        logger.warning(
                            f"Could not decrypt API key for user {user_id}: {e}"
                        )

                return {
                    "cloud_url": result["cloud_url"] or CLOUD_OLLAMA_URL,
                    "local_url": result["local_url"] or LOCAL_OLLAMA_URL,
                    "api_key": api_key,
                    "preferred_endpoint": result["preferred_endpoint"] or "auto",
                }
    except Exception as e:
        logger.warning(f"Could not fetch user Ollama settings from database: {e}")

    # Fall back to global env vars
    return {
        "cloud_url": CLOUD_OLLAMA_URL,
        "local_url": LOCAL_OLLAMA_URL,
        "api_key": API_KEY,
        "preferred_endpoint": "auto",
    }


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

        sr, wav = safe_generate_speech_optimized(
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
            query=req.query, model=req.model, enable_streaming=True
        )

        if hasattr(response, "__aiter__"):
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
                    "Content-Type": "text/event-stream",
                },
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
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"Advanced fact-check error: {e}")
        return {"error": f"Advanced fact-check failed: {str(e)}"}


@app.post("/api/research/advanced-compare", tags=["research"])
async def advanced_compare(
    topics: List[str], context: str = None, model: str = "mistral"
):
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
            "timestamp": datetime.now().isoformat(),
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
            "disk_usage": psutil.disk_usage("/").percent,
        }

        return ResearchStatsResponse(
            pipeline_stats=stats.get("advanced_pipeline_stats", {}),
            cache_stats=cache_stats,
            system_info=system_info,
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
                "advanced_pipeline": "available",
            },
            "timestamp": datetime.now().isoformat(),
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
            "timestamp": datetime.now().isoformat(),
        }


# ─── Vibe Coding Endpoints ─────────────────────────────────────────────────────

# Vibe coding endpoint moved to vibecoding.commands

# Voice transcribe endpoint moved to vibecoding.commands

# Run command endpoint moved to vibecoding.commands

# Save file endpoint moved to vibecoding.commands

# ─── Vibe Agent Helper Functions moved to vibecoding.core ─────────────────────
