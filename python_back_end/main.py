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
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
import asyncio, uvicorn, os, sys, tempfile, uuid, base64, io, logging, re, requests, random, json, httpx
import hmac
from PIL import Image

# Import optimized auth module
from auth_optimized import get_current_user_optimized, auth_optimizer, get_auth_stats

# Load environment variables from .env file
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # Will log after logger is set up

# ─── Canonical model-provider base URL (plug-and-play) ─────────────────────────
# The bundled `ollama` compose service is gone (phase A5): the user brings their
# own OpenAI-compatible server and compose passes its address as
# HARVIS_LLM_BASE_URL, with OLLAMA_URL kept as a legacy alias. Dozens of modules
# still read os.getenv("OLLAMA_URL", "http://ollama:11434") at import time —
# normalising the environment HERE, before any of them import, makes
# HARVIS_LLM_BASE_URL the canonical source everywhere at once and retires the
# dead `ollama` hostname. host.docker.internal resolves from inside the
# container via extra_hosts (["host.docker.internal:host-gateway"]).
_LLM_DEFAULT_BASE_URL = "http://host.docker.internal:11434"
HARVIS_LLM_BASE_URL = (
    os.getenv("HARVIS_LLM_BASE_URL") or os.getenv("OLLAMA_URL") or _LLM_DEFAULT_BASE_URL
).rstrip("/")
os.environ["HARVIS_LLM_BASE_URL"] = HARVIS_LLM_BASE_URL
os.environ["OLLAMA_URL"] = HARVIS_LLM_BASE_URL
# "Explicitly configured" cannot be read off env presence: compose always sets
# OLLAMA_URL, defaulting it to _LLM_DEFAULT_BASE_URL when .env names no provider.
# So the honest split is: pointing anywhere OTHER than the default guess means
# the operator configured a provider; the default guess itself means "nothing
# configured, probing the conventional host port". /api/ollama-models and
# /api/health/services use this to tell "provider down" from "no provider".
LLM_PROVIDER_EXPLICITLY_CONFIGURED = HARVIS_LLM_BASE_URL != _LLM_DEFAULT_BASE_URL

from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
import asyncpg
from gemini_api import query_gemini, is_gemini_configured
from moonshot_api import (
    MoonshotClient,
    is_moonshot_model,
    get_moonshot_model_id,
    MOONSHOT_BASE_URL,
    _key_fingerprint,
)
from typing import List, Optional, Dict, Any, Union
from vison_models.llm_connector import (
    query_vision,
    query_llm,
    list_vision_models,
    VISION_ERROR_PREFIX,
)

# Import workspace (Harvis Workspaces / OpenClaw integration)
from workspace import workspace_router
from workspace.model_proxy import model_proxy_router
from workspace.github_proxy import github_proxy_router
from workspace.rag_proxy import rag_proxy_router
from workspace.kubectl_proxy import kubectl_proxy_router
from workspace.repo_manager import repo_manager_router
from vibecoding.auth_github import router as auth_github_router, auth_router as auth_github_callback_router
from workspace.terminal_routes import router as workspace_terminal_router
from workspace.harvis_trace import harvis_trace_router
from workspace.harvis_exec import harvis_exec_router
from workspace.harvis_jobs import harvis_jobs_router
from workspace.skill_extractor import harvis_skill_extract_router  # Phase F: run → draft skill
from workspace.harvis_readiness import harvis_readiness_router  # Phases I/H/G: readiness + provider catalog
from image.harvis_image import harvis_image_router  # Image-gen v0: gated txt2img → workspace artifact
from vibecoding.terminal_sessions import router as harvis_terminal_sessions_router

# Import tools routers
from tools import maps_router, openclaw_proxy_router, browser_proxy_router, opencode_llm_router, discord_proxy_router

# Import vibecoding routers
from vibecoding import (
    sessions_router,
    models_router,
    execution_router,
    files_router,
    commands_router,
    containers_router,
    terminal_router,
    ai_assistant_router,
    file_api_router,
    user_prefs_router,
    proxy_router,
    repo_import_router,
    ide_ai_router,
)
from vibecoding.core import initialize_vibe_agent
from file_processing import (
    extract_text_from_file,
    convert_file_to_images,
    is_vision_compatible_file,
)

# Import artifacts module for document/website generation
from artifacts import (
    artifact_router,
    extract_artifact_manifest,
    clean_response_content,
    ArtifactManifest,
    ArtifactStorage,
)
from artifacts.manifest_parser import extract_nextjs_project_from_codeblocks
from artifacts.code_generator import (
    generate_document_from_code,
    extract_document_code,
    get_output_filename,
    auto_detect_document_type,
)
from artifacts.build_manager import ArtifactBuildManager

# Initialize artifact storage
artifact_storage = ArtifactStorage()

# Build manager will be initialized in lifespan with db pool
artifact_build_manager = None

from pydantic import BaseModel, Field
import soundfile as sf

# The entrypoint importing torch at module scope is what made a torch-free
# backend impossible: nothing else mattered while `import main` needed it.
# model_manager already resolves this to the real torch when it is installed and
# to a null object that answers `cuda.is_available() == False` when it is not, so
# every `torch.cuda.*` call below keeps working either way — the GPU bookkeeping
# just becomes a no-op instead of an ImportError.
from model_manager import torch

# ─── Authentication Setup ──────────────────────────────────────────────────────
SECRET_KEY = os.getenv("JWT_SECRET", "key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))  # 7 days

# Temporary logging to verify JWT secret is loaded
print(f"Backend JWT_SECRET loaded: {'set' if SECRET_KEY and SECRET_KEY != 'key' else 'MISSING/DEFAULT'} (len {len(SECRET_KEY)})")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ─── API Key Encryption Setup ──────────────────────────────────────────────────
from cryptography.fernet import Fernet
import hashlib

# Generate or load encryption key for API keys
# Use JWT_SECRET as base to derive encryption key (ensures it's consistent across restarts)
API_KEY_ENCRYPTION_SECRET = os.getenv("API_KEY_ENCRYPTION_SECRET", SECRET_KEY)
# Derive a 32-byte key using SHA-256
_api_key_encryption_key = hashlib.sha256(API_KEY_ENCRYPTION_SECRET.encode()).digest()
# Create Fernet key (base64 encoded 32-byte key)
_api_key_fernet_key = base64.urlsafe_b64encode(_api_key_encryption_key)
_api_key_cipher = Fernet(_api_key_fernet_key)


def encrypt_api_key(api_key: str) -> str:
    """Encrypt an API key using Fernet symmetric encryption."""
    if not api_key:
        logger.warning("encrypt_api_key: Empty API key provided")
        return ""

    # SECURITY: never log key material (not even a preview/length) — logs are a lower-trust sink.
    encrypted = _api_key_cipher.encrypt(api_key.encode())
    encrypted_b64 = base64.urlsafe_b64encode(encrypted).decode()
    logger.debug("encrypt_api_key: encrypted a credential")
    return encrypted_b64


def decrypt_api_key(encrypted_key: str) -> str:
    """Decrypt an API key that was encrypted with encrypt_api_key."""
    if not encrypted_key:
        logger.warning("decrypt_api_key: Empty encrypted key provided")
        return ""
    try:
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_key.encode())
        decrypted = _api_key_cipher.decrypt(encrypted_bytes)
        return decrypted.decode()
    except Exception as e:
        # SECURITY: log only the failure TYPE — never the key material or its length/prefix.
        logger.warning("decrypt_api_key: decryption failed (%s)", type(e).__name__)
        return ""


async def get_user_api_key(
    pool, user_id: int, provider_name: str
) -> Optional[Dict[str, Any]]:
    """Get a user's API key for a specific provider."""
    # DEBUG, not INFO/WARNING: this runs on every model-catalog poll for every
    # provider, and "no key configured" is the normal state for any provider the
    # user hasn't connected — not a warning. At INFO it drowned the boot log.
    logger.debug("get_user_api_key: looking up %s key for user %s", provider_name, user_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, provider_name, api_key_encrypted, api_url, is_active, created_at, updated_at
            FROM user_api_keys
            WHERE user_id = $1 AND provider_name = $2 AND is_active = TRUE
            """,
            user_id,
            provider_name,
        )
        if row:
            encrypted_key = row["api_key_encrypted"]
            decrypted_key = decrypt_api_key(encrypted_key)
            logger.debug(
                "get_user_api_key: %s key resolved for user %s (decrypt %s)",
                provider_name, user_id, "ok" if decrypted_key else "FAILED",
            )
            return {
                "id": row["id"],
                "provider_name": row["provider_name"],
                "api_key": decrypted_key,
                "api_url": row["api_url"],
                "is_active": row["is_active"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        logger.debug("get_user_api_key: no %s key for user %s", provider_name, user_id)
        return None


# Images storage directory (mounted via PVC in K8s)
IMAGES_DIR = os.getenv("IMAGES_DIR", "/app/images")
# OWUI file-attachment storage (uploads via POST /api/v1/files/). Bytes live here,
# metadata in the owui_files table. Persisted volume in prod; /app survives restart.
OWUI_FILES_DIR = os.getenv("OWUI_FILES_DIR", "/app/owui_files")
os.makedirs(IMAGES_DIR, exist_ok=True)
print(f"Images directory: {IMAGES_DIR}")
security = HTTPBearer(auto_error=False)

# ─── RAG Configuration ─────────────────────────────────────────────────────────
# Centralized config for RAG retrieval - supports environment variable overrides
RAG_CONFIG = {
    "default_k": int(os.getenv("RAG_DEFAULT_K", "5")),
    "score_threshold": float(os.getenv("RAG_SCORE_THRESHOLD", "0.35")),
    "max_context_length": int(os.getenv("RAG_MAX_CONTEXT_LENGTH", "4000")),
}

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
    # Presence, never the token. This used to log the whole
    # HTTPAuthorizationCredentials object, so every authenticated request wrote a
    # live bearer token into the container log — replayable by anyone who can read
    # `docker logs` or whatever ships them, for the rest of its lifetime.
    logger.info("get_current_user: bearer header %s", "present" if credentials else "absent")
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
        # Claim names only — the payload itself can carry more than the subject.
        logger.debug("JWT payload claims: %s", sorted(payload))
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


# ─── Authorization ──────────────────────────────────────────────────────────────
# Server-side admin gate. The SvelteKit route guards on /admin and /workspace only
# decide what the browser renders — they cannot stop a direct API call with a valid
# token. Any admin-shaped or server-wide-config route must depend on this, not on
# the client behaving. See owui_compat/authz.py for how admin identity is derived
# (same single source the OWUI facade uses for the UI, so the two cannot disagree).
from owui_compat.authz import make_require_admin  # noqa: E402

require_admin = make_require_admin(get_current_user)

from setup_flow import (  # noqa: E402
    _SERVICE_PROFILE,
    create_setup_router,
    service_expected,
)
# Router include is deferred until after ``app = FastAPI(...)`` below.


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
    generate_speech_optimized,
    generate_speech_unified,
    unload_tts_model,
    unload_whisper_model,
    unload_qwen_tts_model,
    get_gpu_memory_stats,
    check_memory_pressure,
    auto_cleanup_if_needed,
    set_active_tts_engine,
    get_active_tts_engine,
    get_available_tts_engines,
)

# Speech-to-text goes through the provider client, not model_manager directly, so
# HARVIS_STT_PROVIDER can point these routes at a sidecar or at the browser
# without touching them. Default is `local`, i.e. the in-process Whisper this
# used to call.
from transcription import (
    TranscriptionUnavailable,
    status as transcription_status,
    transcribe as transcribe_audio,
)
# Aliased `tts_synthesize`, not `synthesize_speech`: main.py already defines a
# route handler by that name further down, and a module-level def silently wins
# over an import at call time.
from synthesis import SynthesisUnavailable, synthesize as tts_synthesize
import synthesis


# TTS Helper Function with graceful error handling
def safe_generate_speech_optimized(
    text,
    audio_prompt=None,
    exaggeration=0.5,
    temperature=0.3,
    cfg_weight=0.7,
    auto_unload=True,
    tts_engine="qwen",
):
    """Generate speech with graceful error handling - never crashes the app.

    Args:
        text: Text to synthesize
        audio_prompt: Voice prompt for cloning (Chatterbox only)
        exaggeration: Voice expressiveness (Chatterbox only)
        temperature: Generation temperature
        cfg_weight: CFG weight (Chatterbox only)
        auto_unload: Unload TTS after generation
        tts_engine: "qwen" or "chatterbox" TTS engine selection
    """
    try:
        # Use unified TTS generation that supports both engines
        result = generate_speech_unified(
            text=text,
            engine=tts_engine,
            audio_prompt=audio_prompt,
            exaggeration=exaggeration,
            temperature=temperature,
            cfg_weight=cfg_weight,
            auto_unload=auto_unload,
        )
        if result is None or result == (None, None):
            logger.warning(
                f"⚠️ TTS ({tts_engine}) unavailable - skipping audio generation"
            )
            return None, None
        return result
    except Exception as tts_e:
        logger.error(f"❌ TTS ({tts_engine}) generation failed gracefully: {tts_e}")
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


class _VibeSchemaPresent(Exception):
    """Not an error — the table is already there, so skip applying its DDL."""


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create connection pool
    global db_pool, chat_history_manager
    try:
        database_url = os.getenv(
            "DATABASE_URL", "postgresql://pguser:pgpassword@pgsql:5432/database"
        )
        app.state.pg_pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=5,  # Increased from 1 for faster RAG queries
            max_size=20,  # Increased from 10 for concurrent RAG operations
            command_timeout=30,
            max_inactive_connection_lifetime=300,  # 5 minutes - clean up stale connections
        )
        logger.info("✅ Database connection pool created")

        # Repo Runner: periodically reap idle / finished preview sandboxes so the
        # advertised idle-teardown actually fires (only when the feature is on).
        try:
            from owui_compat import repo_sandbox as _repo_sandbox
            if _repo_sandbox.run_enabled():
                asyncio.create_task(_repo_sandbox.run_sweeper())
                logger.info("✅ Repo-sandbox idle sweeper started")
        except Exception as _exc:  # noqa: BLE001
            logger.warning("repo-sandbox sweeper not started: %s", _exc)

        # Workspace terminals: periodic janitor — stops idle terminal
        # containers and prunes finished background-job records (Phase E1).
        try:
            from workspace.terminal_container import get_terminal_manager

            async def _terminal_sweeper() -> None:
                while True:
                    await asyncio.sleep(300)
                    try:
                        await get_terminal_manager().sweep_idle()
                    except Exception as _sweep_exc:  # noqa: BLE001
                        logger.warning("terminal sweep_idle failed: %s", _sweep_exc)

            asyncio.create_task(_terminal_sweeper())
            logger.info("✅ Workspace-terminal idle sweeper started")
        except Exception as _exc:  # noqa: BLE001
            logger.warning("terminal sweeper not started: %s", _exc)

        # Ensure OpenClaw web tool audit + prefs columns exist (idempotent)
        try:
            async with app.state.pg_pool.acquire() as conn:
                # Core schema (users/chat_sessions/chat_messages/artifacts/…).
                # Fully idempotent; heals volumes that predate the initdb
                # mounts of all_schemas_safe.sql.
                _core_schema_path = os.path.join(
                    os.path.dirname(__file__), "all_schemas_safe.sql"
                )
                # Guarded so a core-schema hiccup cannot silently skip EVERY
                # block below it (the 010-015 sweep included) — that failure
                # mode is exactly how `relation "cron_jobs" does not exist`
                # loops on a box where this file failed once at boot. On a
                # fresh volume initdb already ran this same file, so continuing
                # past a failure here is safe, not optimistic.
                try:
                    with open(_core_schema_path, "r") as _csf:
                        await conn.execute(_csf.read())
                    logger.info("✅ Core schema ensured (all_schemas_safe.sql)")
                except Exception as _core_err:  # noqa: BLE001
                    logger.error(
                        "❌ Core schema (all_schemas_safe.sql) did not apply "
                        "(continuing to migrations): %s",
                        _core_err,
                    )

                # Migrations 010-015 create tables (user_openclaw_config, cron_jobs,
                # user_memory, mcp_servers, messaging_platforms, user_soul) that no
                # initdb mount and no other startup block provisions — a fresh clone
                # otherwise spams `relation "cron_jobs" does not exist` and
                # cron/messaging features break. run_migrations.py exists but is
                # never invoked. Apply just these six here: all are verified
                # idempotent (CREATE ... IF NOT EXISTS), so this heals fresh AND
                # pre-existing volumes. Per-file try/except so one bad file can't
                # abort boot. Most of 001-009 include un-guarded ALTERs and are
                # deliberately NOT swept in — the exception is the podcast trio
                # (005-007), which IS idempotent and is applied further below,
                # after the notebooks schema its FK depends on.
                #
                # 010 was missing from this list even though it is idempotent, so
                # user_openclaw_config never existed on a fresh volume and every BYO
                # OpenClaw lookup failed — which is what surfaced as the pairing
                # regression. It is a plain CREATE TABLE/INDEX IF NOT EXISTS plus a
                # CREATE OR REPLACE FUNCTION and a DROP-then-CREATE trigger.
                _mig_dir = os.path.join(os.path.dirname(__file__), "migrations")
                for _mig_name in (
                    "010_user_openclaw_config.sql",
                    "011_messaging_platforms.sql",
                    "012_user_memory.sql",
                    "013_mcp_servers.sql",
                    "014_cron_jobs.sql",
                    "015_user_soul.sql",
                    "016_inference_nodes.sql",
                ):
                    _mig_path = os.path.join(_mig_dir, _mig_name)
                    try:
                        with open(_mig_path, "r") as _mf:
                            await conn.execute(_mf.read())
                    except FileNotFoundError:
                        # A missing file here means the deploy did not ship
                        # migrations/ (image built from a partial context, or a
                        # k8s mount list that names files individually). The
                        # old silent `pass` made that indistinguishable from
                        # success — and the table it should have created then
                        # fails at USE time (cron_jobs et al.), far from the
                        # cause. Loud, every boot, on purpose.
                        logger.warning(
                            "Migration file missing — table(s) it creates will "
                            "not exist: %s",
                            _mig_path,
                        )
                    except Exception as _mig_err:  # noqa: BLE001
                        logger.warning(
                            "Migration %s did not apply cleanly (continuing): %s",
                            _mig_name,
                            _mig_err,
                        )
                logger.info("✅ Idempotent migrations 010-016 ensured")

                # vibecoding_sessions. The /api/vibecode/sessions* routes are
                # mounted on every boot and every one of them queries this table,
                # but nothing created it: migration 001 only ALTERs a table it
                # assumes already exists, and the file that does CREATE it
                # (vibecoding_sessions_schema.sql) has exactly one caller —
                # init_vibecode_db.py, which no startup path, entrypoint or
                # compose command ever runs. On this database the table is simply
                # absent, so opening a VibeCode session 500s. Applied here, beside
                # the other idempotent SQL, so a fresh clone and an old volume
                # both end up with it.
                # Heal-if-absent, not run-every-boot: this file is baked into the
                # image rather than bind-mounted, so an older copy without the
                # DROP TRIGGER guards will still be on disk in existing containers
                # and re-running it there fails on "trigger already exists". Gating
                # on the table means correctness never depends on which copy of the
                # SQL the container happens to hold.
                _vibe_schema_path = os.path.join(
                    os.path.dirname(__file__), "vibecoding_sessions_schema.sql"
                )
                try:
                    if await conn.fetchval(
                        "SELECT to_regclass('public.vibecoding_sessions')"
                    ):
                        logger.info("✅ vibecoding_sessions already present")
                        raise _VibeSchemaPresent
                    with open(_vibe_schema_path, "r") as _vsf:
                        await conn.execute(_vsf.read())
                    logger.info("✅ vibecoding_sessions schema created")
                except _VibeSchemaPresent:
                    pass
                except FileNotFoundError:
                    logger.warning(
                        "vibecoding_sessions_schema.sql missing — VibeCode "
                        "session endpoints will fail: %s",
                        _vibe_schema_path,
                    )
                except Exception as _vibe_err:  # noqa: BLE001
                    logger.warning(
                        "vibecoding_sessions schema did not apply cleanly "
                        "(continuing): %s",
                        _vibe_err,
                    )

                # Instance-level key/value settings (admin_user_id, …).
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS instance_settings (
                      key TEXT PRIMARY KEY,
                      value TEXT,
                      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )
                _admin_id_row = await conn.fetchval(
                    "SELECT value FROM instance_settings WHERE key = 'admin_user_id'"
                )
                if _admin_id_row and str(_admin_id_row).isdigit():
                    from owui_compat import translate as _owui_translate
                    _owui_translate.add_persisted_admin_id(int(_admin_id_row))
                    logger.info(f"✅ Persisted admin user id loaded: {_admin_id_row}")

                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS openclaw_tool_audit (
                      id SERIAL PRIMARY KEY,
                      ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                      session_key TEXT,
                      tool TEXT NOT NULL,
                      input JSONB DEFAULT '{}'::jsonb,
                      output_meta JSONB DEFAULT '{}'::jsonb,
                      status_code INTEGER,
                      error TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_oc_tool_audit_ts ON openclaw_tool_audit(ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_oc_tool_audit_tool ON openclaw_tool_audit(tool, ts DESC);
                    """
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_prefs (
                      id SERIAL PRIMARY KEY,
                      user_id INTEGER NOT NULL UNIQUE,
                      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    DO $$
                    BEGIN
                      IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='user_prefs' AND column_name='theme'
                      ) THEN
                        ALTER TABLE user_prefs ADD COLUMN theme TEXT DEFAULT 'dark';
                      END IF;
                      IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='user_prefs' AND column_name='left_panel_width'
                      ) THEN
                        ALTER TABLE user_prefs ADD COLUMN left_panel_width INTEGER DEFAULT 280;
                      END IF;
                      IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='user_prefs' AND column_name='right_panel_width'
                      ) THEN
                        ALTER TABLE user_prefs ADD COLUMN right_panel_width INTEGER DEFAULT 384;
                      END IF;
                      IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='user_prefs' AND column_name='terminal_height'
                      ) THEN
                        ALTER TABLE user_prefs ADD COLUMN terminal_height INTEGER DEFAULT 200;
                      END IF;
                      IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='user_prefs' AND column_name='default_model'
                      ) THEN
                        ALTER TABLE user_prefs ADD COLUMN default_model VARCHAR(100) DEFAULT 'mistral';
                      END IF;
                      IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='user_prefs' AND column_name='font_size'
                      ) THEN
                        ALTER TABLE user_prefs ADD COLUMN font_size INTEGER DEFAULT 14;
                      END IF;
                      IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='user_prefs' AND column_name='default_web_tier'
                      ) THEN
                        ALTER TABLE user_prefs ADD COLUMN default_web_tier TEXT DEFAULT 'tier2';
                      END IF;
                    END $$;
                    """
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workspace_web_caps (
                      workspace_id TEXT PRIMARY KEY,
                      user_id INTEGER NOT NULL,
                      interactive_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                      capability_token TEXT,
                      expires_at TIMESTAMPTZ,
                      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE INDEX IF NOT EXISTS idx_ws_web_caps_user ON workspace_web_caps(user_id, created_at DESC);
                    """
                )
                # OWUI-compat chat persistence (the forked OpenWebUI frontend
                # stores its full chat blob as JSONB; see owui_compat/persistence.py).
                from owui_compat import (
                    CREATE_OWUI_CHATS_SQL,
                    CREATE_OWUI_COMPARISONS_SQL,
                    CREATE_OWUI_FILES_SQL,
                    CREATE_OWUI_FOLDERS_SQL,
                    CREATE_OWUI_KNOWLEDGE_SQL,
                    CREATE_OWUI_SKILLS_SQL,
                    CREATE_OWUI_SUBAGENTS_SQL,
                    CREATE_OWUI_USER_SETTINGS_SQL,
                    CREATE_OWUI_ORCH_POOL_SQL,
                    CAD_SCHEMA_SQL,
                )

                await conn.execute(CREATE_OWUI_CHATS_SQL)
                await conn.execute(CREATE_OWUI_FILES_SQL)
                await conn.execute(CREATE_OWUI_FOLDERS_SQL)
                await conn.execute(CREATE_OWUI_COMPARISONS_SQL)
                await conn.execute(CREATE_OWUI_KNOWLEDGE_SQL)
                await conn.execute(CREATE_OWUI_SKILLS_SQL)
                await conn.execute(CREATE_OWUI_SUBAGENTS_SQL)
                await conn.execute(CREATE_OWUI_USER_SETTINGS_SQL)
                await conn.execute(CREATE_OWUI_ORCH_POOL_SQL)

                # Gate 3: the local CAD lane's store — projects, immutable revisions,
                # build attempts, artifact metadata. Runs unconditionally, unlike the
                # routes: the flag decides whether the lane is reachable, not whether
                # the tables that already hold a user's parts exist. Ordered after
                # all_schemas_safe.sql above, which is what creates users(id).
                for stmt in CAD_SCHEMA_SQL:
                    await conn.execute(stmt)

                # P5 orchestration: agent-run columns on workspace_runs + the
                # workspace_artifacts table (idempotent ALTER/CREATE; workspace_runs
                # itself comes from initdb, so this self-heals the live DB on restart).
                from workspace.orchestration import ORCHESTRATION_SCHEMA_SQL
                await conn.execute(ORCHESTRATION_SCHEMA_SQL)

                # Phase E2: background-job persistence + binary artifact storage.
                # workspace_jobs mirrors the in-memory _jobs registry so jobs
                # survive a backend restart (reattach task below resumes tails);
                # content_bytes stores raw binary artifacts (STL/PNG/…) that
                # can't live in the TEXT content column.
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workspace_jobs (
                        id             TEXT PRIMARY KEY,
                        workspace_id   TEXT NOT NULL,
                        user_id        INT,
                        command        TEXT,
                        workdir        TEXT,
                        status         TEXT,
                        exit_code      INT,
                        base_path      TEXT,
                        container_name TEXT,
                        started_at     TIMESTAMPTZ DEFAULT NOW(),
                        finished_at    TIMESTAMPTZ
                    );
                    CREATE INDEX IF NOT EXISTS idx_workspace_jobs_ws
                        ON workspace_jobs(workspace_id);
                    -- Phase 5 (Build Space): per-job max lifetime, surfaced on the
                    -- job record and enforced by the tail loop's reaper.
                    ALTER TABLE workspace_jobs
                        ADD COLUMN IF NOT EXISTS timeout_secs INT;
                    ALTER TABLE workspace_artifacts
                        ADD COLUMN IF NOT EXISTS content_bytes BYTEA;
                    """
                )

                # Trace-correctness backstop: unique (workspace_id, seq) on
                # workspace_events. GUARDED — skips (with a warning) when
                # pre-allocator duplicate rows exist, never deletes history.
                try:
                    from workspace.events_seq_migration import ensure_events_seq_unique_index
                    await ensure_events_seq_unique_index(conn)
                except Exception as _seq_exc:  # noqa: BLE001
                    logger.warning("⚠️ workspace_events seq-index migration failed: %s", _seq_exc)

                # Open Notebook (RAG notebooks) — self-create the schema (the tables
                # were never applied on this deploy). Idempotent CREATE TABLE/INDEX.
                import os as _os
                _nb_schema_path = _os.path.join(_os.path.dirname(__file__), "notebooks", "schema.sql")
                with open(_nb_schema_path, "r") as _nbf:
                    await conn.execute(_nbf.read())
                logger.info("✅ Notebook schema ensured")

                # Podcast tables (005-007). They belong to the notebooks feature and
                # 005 has an FK to notebooks(id), so they must run AFTER the schema
                # above — which is why they are not in the 010-015 sweep. Nothing
                # else provisions them: no initdb mount, no other startup block, and
                # run_migrations.py is never invoked. On a fresh volume that made
                # every /onb-api podcast call fail with
                # `relation "standalone_podcasts" does not exist`. All three are
                # idempotent (CREATE TABLE/INDEX IF NOT EXISTS, ADD COLUMN IF NOT
                # EXISTS), so this heals fresh AND pre-existing volumes.
                for _pod_mig in (
                    "005_create_notebook_podcasts.sql",
                    "006_create_standalone_podcasts.sql",
                    "007_alter_standalone_podcasts_add_speakers.sql",
                ):
                    _pod_path = _os.path.join(
                        _os.path.dirname(__file__), "migrations", _pod_mig
                    )
                    try:
                        with open(_pod_path, "r") as _pf:
                            await conn.execute(_pf.read())
                    except FileNotFoundError:
                        logger.warning("Podcast migration %s not found", _pod_mig)
                    except Exception as _pod_err:  # noqa: BLE001
                        logger.warning(
                            "Podcast migration %s did not apply cleanly (continuing): %s",
                            _pod_mig,
                            _pod_err,
                        )
                logger.info("✅ Podcast tables ensured (005-007)")

                # Cookbook: ensure the cookbook_nodes table + merge any
                # user-added inference nodes back into the live registry so a
                # LAN GPU box added through the UI survives a restart.
                try:
                    from cookbook import config as _cookbook_config
                    _n = await _cookbook_config.load_persisted_nodes(app.state.pg_pool)
                    logger.info("✅ Cookbook nodes ensured (%d persisted)", _n)
                except Exception as _cb_exc:  # noqa: BLE001
                    logger.warning("⚠️ Cookbook node load failed: %s", _cb_exc)
        except Exception as e:
            logger.warning("⚠️ Failed to init OpenClaw audit/prefs schema: %s", e)

        # Phase E2: reconnect to background jobs that were 'running' when the
        # backend last died. The detached wrappers + their /tmp/harvis-job-*
        # files survive inside the sandbox containers; this finalizes finished
        # ones, resumes tailing live ones, and marks container-less ones lost.
        # Best-effort — a failure here must never block startup. Runs AFTER the
        # migration block above so workspace_jobs is guaranteed to exist.
        try:
            from workspace.terminal_container import get_terminal_manager as _get_term_mgr

            async def _job_reattacher() -> None:
                try:
                    n = await _get_term_mgr().reattach_running_jobs(app.state.pg_pool)
                    if n:
                        logger.info("✅ Reattached %d background job(s) after restart", n)
                except Exception as _re_exc:  # noqa: BLE001
                    logger.warning("background-job reattach failed: %s", _re_exc)

            asyncio.create_task(_job_reattacher())
        except Exception as _exc:  # noqa: BLE001
            logger.warning("job reattacher not started: %s", _exc)

        # Initialize ChatHistoryManager
        db_pool = app.state.pg_pool
        chat_history_manager = ChatHistoryManager(db_pool)
        logger.info("✅ ChatHistoryManager initialized")

        # Attachment ownership (Gate 8A). `vision_to_code/attachments.py` resolves an
        # upload id straight to bytes and hands them to a model or writes them into an
        # agent's working tree, so it must be able to ask who owns one. It deliberately
        # holds no database handle — giving one to the module that also parses untrusted
        # files is the wrong trade — so the app registers the single query it needs.
        # Unregistered, that store refuses every id rather than serving it unchecked.
        try:
            from vision_to_code.attachments import set_owui_owner_lookup

            async def _owui_owner_of(file_id: str):
                async with app.state.pg_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT user_id FROM owui_files WHERE id=$1", file_id
                    )
                return int(row["user_id"]) if row else None

            set_owui_owner_lookup(_owui_owner_of)
            logger.info("✅ Attachment ownership lookup registered")
        except Exception as _exc:  # noqa: BLE001
            logger.warning("attachment ownership lookup NOT registered: %s", _exc)

        # Initialize ArtifactBuildManager for website/app builds
        global artifact_build_manager
        try:
            artifact_build_manager = ArtifactBuildManager(db_pool)
            app.state.artifact_build_manager = artifact_build_manager
            # Start the build queue processor (for K8s deployments)
            if os.environ.get("ENABLE_ARTIFACT_EXECUTOR", "false").lower() == "true":
                await artifact_build_manager.start_queue_processor()
                logger.info("✅ ArtifactBuildManager initialized with queue processor")
            else:
                logger.info(
                    "✅ ArtifactBuildManager initialized (executor disabled - using Sandpack)"
                )
        except Exception as e:
            logger.warning(f"⚠️ ArtifactBuildManager initialization failed: {e}")

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

                    # Initialize multi-collection retriever with centralized config
                    local_rag_retriever = MultiCollectionRetriever(
                        vectordb_adapters=vectordb_adapters,
                        embedding_adapters=embedding_adapters,
                        source_to_model=source_model_mapping,
                        model_to_collection=model_collection_mapping,
                        default_k=RAG_CONFIG["default_k"],
                        score_threshold=RAG_CONFIG["score_threshold"],
                    )
                    logger.info(
                        f"✅ Global Multi-Collection RAG retriever initialized "
                        f"(k={RAG_CONFIG['default_k']}, threshold={RAG_CONFIG['score_threshold']})"
                    )

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

    # Initialize job queue workers for background TTS/Whisper processing
    try:
        from job_queue import init_job_queue, start_tts_worker, start_whisper_worker

        job_queue = await init_job_queue()
        app.state.job_queue = job_queue
        logger.info("✅ Job queue initialized")

        # Start background workers (skipped if external tts-worker pod handles them)
        if os.getenv("DISABLE_LOCAL_TTS_WORKERS", "false").lower() != "true":
            await start_tts_worker()
            await start_whisper_worker()
            logger.info("✅ Job queue workers started (TTS & Whisper)")
        else:
            logger.info(
                "⏭️  Local TTS/Whisper workers disabled (external tts-worker pod)"
            )

    except Exception as e:
        logger.warning(f"⚠️ Job queue initialization failed: {e}")
        # Don't fail startup if job queue doesn't work

    # Discord → Workspace bridge (legacy in-process bot).
    # Phase 1D introduces the messaging-gateway sidecar (plugins/messaging-gateway/)
    # which owns Discord going forward. Until operators flip the cutover env var,
    # this legacy bot remains the active path so existing deploys are unchanged.
    # When MESSAGING_ENABLED_PLATFORMS includes "discord", set
    # DISCORD_WORKSPACE_BOT_LEGACY_ENABLED=false to avoid duplicate replies.
    if os.getenv("DISCORD_WORKSPACE_BOT_LEGACY_ENABLED", "true").lower() == "true":
        try:
            from integrations.discord_workspace_bot import start_discord_workspace_bot

            req = Request(scope={"type": "http", "app": app})
            discord_client = start_discord_workspace_bot(req)
            if discord_client is not None:
                app.state.discord_client = discord_client
                logger.info("✅ Discord workspace bot started (legacy path)")
        except Exception as e:
            logger.warning(f"⚠️ Discord workspace bot failed to start: {e}")
    else:
        logger.info(
            "⏭️  Legacy Discord workspace bot disabled by env "
            "(DISCORD_WORKSPACE_BOT_LEGACY_ENABLED=false). "
            "Discord traffic is expected to flow through harvis-messaging-gateway."
        )

    # Per-workspace terminal — startup readiness probe (option 2: auto-detect).
    # Default-on; the env var is a kill-switch. Logs a clear reason if it can't
    # actually run so the operator knows without poking the health endpoint.
    try:
        from workspace.terminal_container import terminal_status as _term_status
        ts = await _term_status(force_probe=True)
        if ts["available"]:
            logger.info(
                "✅ Workspace terminal ready (image=%s, network=%s)",
                ts["probe"]["base_image"], ts["probe"]["network"],
            )
        elif ts["enabled"]:
            logger.warning(
                "⚠️ Workspace terminal not ready: %s",
                ts["reason"],
            )
        else:
            logger.info("⏭️  Workspace terminal disabled by HARVIS_TERMINAL_ENABLED=false")
    except Exception as e:
        logger.warning(f"⚠️ Workspace terminal readiness probe failed: {e}")

    # Phase 3B — discover and load plugins declared via plugin.yaml.
    # No-op when HARVIS_PLUGINS_ENABLED is unset; the loader fails-open on
    # any per-plugin import / env-availability error so one broken plugin
    # never blocks startup.
    try:
        from plugins.core.loader import load_all as _load_plugins
        _loaded = _load_plugins()
        app.state.loaded_plugins = _loaded
        _summary = {
            p.status: 1 + sum(1 for q in _loaded if q.status == p.status and q is not p)
            for p in _loaded
        }
        if _loaded:
            logger.info(
                "🔌 plugins discovered: %d (statuses: %s)",
                len(_loaded),
                {s: sum(1 for p in _loaded if p.status == s) for s in {p.status for p in _loaded}},
            )
    except Exception as e:
        logger.warning(f"⚠️ Plugin loader failed: {e}")

    # Phase 6B — start the cron tick background loop if HARVIS_CRON_ENABLED=true.
    # Default off so existing deployments are unchanged. Wrapped in try/except so
    # a broken cron runtime doesn't block backend startup.
    try:
        # Inference nodes (plugins/inference_nodes): hand the plugin the app so DB-registered
        # nodes can be read from the pool. Env-configured nodes work without this.
        try:
            from plugins.inference_nodes import attach as _attach_inference_nodes
            _attach_inference_nodes(app)
        except Exception as e:
            logger.warning(f"⚠️ inference_nodes plugin attach failed: {e}")
        from plugins.cron.runtime import start_cron_tick_loop
        app.state.cron_tick_task = await start_cron_tick_loop(app)
    except Exception as e:
        logger.warning(f"⚠️ Cron tick loop failed to start: {e}")
        app.state.cron_tick_task = None

    # Repo-sandbox idle sweeper — reaps idle preview dev-server containers.
    # Wrapped in try/except so a missing/broken repo_sandbox never blocks startup.
    try:
        from owui_compat import repo_sandbox
        app.state.repo_sandbox_sweeper_task = asyncio.create_task(repo_sandbox.run_sweeper())
        logger.info("🧹 Repo-sandbox idle sweeper started")
    except Exception as e:
        logger.warning(f"⚠️ Repo-sandbox sweeper failed to start: {e}")
        app.state.repo_sandbox_sweeper_task = None

    # VibeCode preview sweeper — same job for the Build/Code tab's own sandboxes.
    # Only started when the feature is on: an always-running loop over an empty
    # table is pure noise.
    try:
        from owui_compat import workspace_sandbox
        if workspace_sandbox.run_enabled():
            app.state.vibecode_sandbox_sweeper_task = asyncio.create_task(
                workspace_sandbox.run_sweeper()
            )
            logger.info("🧹 VibeCode preview idle sweeper started")
        else:
            app.state.vibecode_sandbox_sweeper_task = None
    except Exception as e:
        logger.warning(f"⚠️ VibeCode preview sweeper failed to start: {e}")
        app.state.vibecode_sandbox_sweeper_task = None

    yield

    # Shutdown: stop repo-sandbox sweeper
    try:
        sweeper_task = getattr(app.state, "repo_sandbox_sweeper_task", None)
        if sweeper_task is not None:
            sweeper_task.cancel()
        vibe_task = getattr(app.state, "vibecode_sandbox_sweeper_task", None)
        if vibe_task is not None:
            vibe_task.cancel()
    except Exception as e:
        logger.warning(f"⚠️ Repo-sandbox sweeper shutdown error: {e}")

    # Shutdown: stop cron tick loop
    try:
        from plugins.cron.runtime import stop_cron_tick_loop
        await stop_cron_tick_loop(getattr(app.state, "cron_tick_task", None))
    except Exception as e:
        logger.warning(f"⚠️ Cron tick loop shutdown error: {e}")

    # Shutdown: stop Discord bot
    try:
        discord_client = getattr(app.state, "discord_client", None)
        if discord_client is not None:
            await discord_client.close()
            logger.info("✅ Discord workspace bot stopped")
    except Exception as e:
        logger.warning(f"⚠️ Discord bot shutdown error: {e}")

    # Shutdown: close connection pool
    if hasattr(app.state, "pg_pool"):
        await app.state.pg_pool.close()
        logger.info("✅ Database connection pool closed")

    # Shutdown job queue
    try:
        from job_queue import shutdown_job_queue

        await shutdown_job_queue()
        logger.info("✅ Job queue shut down")
    except Exception as e:
        logger.warning(f"⚠️ Job queue shutdown error: {e}")


app = FastAPI(lifespan=lifespan)


def _pretty_ollama_name(name: str) -> str:
    """Display label for an Ollama model — KEEP the variant tag (e4b/e2b/32b/
    7b-instruct/…) so similar models stay distinguishable in the picker; only
    drop the redundant ':latest'. Without this, gemma4:e4b and gemma4:e2b both
    collapse to 'gemma4' and you can't tell them apart."""
    return name[: -len(":latest")] if name.endswith(":latest") else name


# ─── Models Endpoint ──────────────────────────────────────────────────────────
# NOTE: native shape is `{"models": [...]}`. The OWUI-compat facade owns the bare
# `GET /api/models` (OWUI shape `{"data": [...]}`) and calls list_models() in-process
# to translate. This route is renamed to /native so the facade can claim the bare path.
@app.get("/api/models/native", tags=["models"])
async def list_models(
    request: Request, current_user: UserResponse = Depends(get_current_user)
):
    """
    Fetch available models from all backends and return them for the frontend selector.
    Uses caching to reduce latency. Results are cached for 60 seconds.
    """
    # Check cache first
    cached = _get_cached_models()
    if cached is not None:
        # Still need to add user-specific models (Moonshot/NVIDIA) if applicable
        pool = getattr(request.app.state, "pg_pool", None)
        user_models = []

        if pool:
            # Check Moonshot
            try:
                moonshot_config = await get_user_api_key(
                    pool, current_user.id, "moonshot"
                )
                if moonshot_config and moonshot_config.get("api_key"):
                    user_models.extend(
                        [
                            {"name": "kimi-k2.5", "provider": "moonshot"},
                            {"name": "kimi-k2", "provider": "moonshot"},
                        ]
                    )
            except Exception:
                pass

            # Check NVIDIA
            try:
                nvidia_config = await get_user_api_key(pool, current_user.id, "nvidia")
                if nvidia_config and nvidia_config.get("api_key"):
                    user_models.append({"name": "nvidia-kimi", "provider": "nvidia"})
            except Exception:
                pass

        # Merge user-specific models into cached list
        existing_names = {m["name"] for m in cached.get("models", [])}
        for um in user_models:
            if um["name"] not in existing_names:
                if um["provider"] == "moonshot":
                    cached["models"].append(
                        {
                            "name": um["name"],
                            "displayName": f"{um['name'].replace('kimi-', 'Kimi ').title()} (Moonshot)",
                            "size": "Cloud",
                            "status": "available",
                            "provider": "moonshot",
                        }
                    )
                elif um["provider"] == "nvidia":
                    cached["models"].append(
                        {
                            "name": um["name"],
                            "displayName": "Kimi K2.5 (NVIDIA NIM)",
                            "size": "Cloud",
                            "status": "available",
                            "provider": "nvidia",
                        }
                    )

        cached["models"].sort(key=lambda x: x["name"])
        return cached

    formatted_models = []

    # ── Ollama hosts (laptop + RTX 5080 rig), probed live and reported honestly ────
    # One probe per host through owui_compat.ollama_hosts, which is also what the CAD
    # lane and model routing use — so a model cannot be "installed" for one lane and
    # missing for another. Two things this deliberately does that the old per-host
    # blocks did not:
    #
    #   • a model carries the host that serves it, so the picker can say where it runs
    #     rather than implying every tag is on this machine;
    #   • a host that is down does not make its models vanish. They come back marked
    #     `unreachable` with the reason, because a model silently disappearing from the
    #     picker reads to a user as Harvis losing it, and they go looking in the wrong
    #     place. Only tags that host previously served and no live host has are listed.
    try:
        from owui_compat import ollama_hosts as _oh

        _snap = await _oh.snapshot()
        for _st in _snap.values():
            if not _st.reachable:
                logger.warning(
                    "Ollama host %s (%s) unreachable: %s", _st.name, _st.base_url, _st.error
                )
                continue
            for model_name in sorted(_st.tags):
                if not any(e["name"] == model_name for e in formatted_models):
                    formatted_models.append(
                        {
                            "name": model_name,
                            "displayName": f"{_pretty_ollama_name(model_name)} ({_st.label})",
                            "size": (
                                _parse_model_size(_st.sizes[model_name])
                                if model_name in _st.sizes else ""
                            ),
                            "status": "available",
                            "provider": "ollama" if _st.name == "laptop" else "ollama-desktop",
                            "host": _st.name,
                            # How much conversation this model can actually hold on this
                            # host — trained window capped by what the daemon serves. The
                            # chat's usage meter and the model-swap fit test both read it;
                            # absent when the host could not be asked.
                            "contextLength": _st.ctx.get(model_name),
                        }
                    )
                if _st.name == "laptop":
                    # Chat routing reads this to decide a request goes back to Ollama.
                    # Only the laptop's tags belong in it — it names what this box can
                    # serve directly, not what exists somewhere on the network.
                    LOCAL_OLLAMA_MODELS_CACHE.add(model_name)
            logger.info("Added %d Ollama models from %s (%s)",
                        len(_st.tags), _st.base_url, _st.name)

        for model_name, _st in await _oh.unreachable_models():
            if not any(e["name"] == model_name for e in formatted_models):
                formatted_models.append(
                    {
                        "name": model_name,
                        "displayName": f"{_pretty_ollama_name(model_name)} ({_st.label})",
                        "size": "",
                        "status": "unreachable",
                        "provider": "ollama" if _st.name == "laptop" else "ollama-desktop",
                        "host": _st.name,
                        "description": f"{_st.label} is not answering ({_st.error})",
                    }
                )
    except Exception as e:
        logger.warning(f"Could not enumerate Ollama hosts: {e}")

    # ── Inference nodes (plugins/inference_nodes): FreeToken / vLLM / llama-server boxes
    # registered by env or through the admin API. Same honesty as the Ollama hosts above:
    # a node that is down keeps its models listed, greyed out, rather than losing them.
    try:
        from plugins.inference_nodes import snapshot as _nodes_snapshot
        from plugins.inference_nodes import unreachable_models as _nodes_unreachable

        for _ns in (await _nodes_snapshot()).values():
            if not _ns.reachable:
                logger.warning("Inference node %s (%s) unreachable: %s",
                               _ns.spec.name, _ns.spec.base_url, _ns.error)
                continue
            for model_name in sorted(_ns.models):
                if not any(e["name"] == model_name for e in formatted_models):
                    formatted_models.append(
                        {
                            "name": model_name,
                            "displayName": f"{model_name} ({_ns.spec.label})",
                            "size": "",
                            "status": "available",
                            "provider": "inference-node",
                            "host": _ns.spec.name,
                            "description": _ns.spec.hardware,
                            # As reported by the node's /v1/models — FreeToken gives the
                            # served window, not a trained one, so no cap is applied.
                            "contextLength": _ns.ctx.get(model_name),
                        }
                    )
            logger.info("Added %d models from inference node %s (%s)",
                        len(_ns.models), _ns.spec.name, _ns.spec.base_url)

        for model_name, _ns in await _nodes_unreachable():
            if not any(e["name"] == model_name for e in formatted_models):
                formatted_models.append(
                    {
                        "name": model_name,
                        "displayName": f"{model_name} ({_ns.spec.label})",
                        "size": "",
                        "status": "unreachable",
                        "provider": "inference-node",
                        "host": _ns.spec.name,
                        "description": f"{_ns.spec.label} is not answering ({_ns.error})",
                    }
                )
    except Exception as e:
        logger.warning(f"Could not enumerate inference nodes: {e}")

    # Fetch from llama-server (local GPU via llama.cpp)
    try:
        llama_url = os.getenv("LLAMA_URL", "http://host.docker.internal:8080/v1")
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{llama_url}/models", timeout=5.0)

        if resp.status_code == 200:
            data = resp.json()
            for m in data.get("data", []):
                model_id = m.get("id", "unknown")
                if not any(
                    existing["name"] == model_id for existing in formatted_models
                ):
                    formatted_models.append(
                        {
                            "name": model_id,
                            "displayName": f"{model_id} (Local GPU)",
                            "size": "8GB",
                            "status": "available",
                            "provider": "llama-server",
                        }
                    )
            logger.info(f"Added {len(data.get('data', []))} llama-server models")
    except Exception as e:
        logger.warning(f"Could not connect to llama-server: {e}")

    # Fetch from vLLM (fast local inference)
    try:
        vllm_url = os.getenv("VLLM_URL", "http://host.docker.internal:8001/v1")
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{vllm_url}/models", timeout=5.0)

        if resp.status_code == 200:
            data = resp.json()
            for m in data.get("data", []):
                model_id = m.get("id", "unknown")
                if not any(
                    existing["name"] == model_id for existing in formatted_models
                ):
                    formatted_models.append(
                        {
                            "name": model_id,
                            "displayName": f"{model_id} (vLLM)",
                            "size": "8GB",
                            "status": "available",
                            "provider": "vllm",
                        }
                    )
            logger.info(f"Added {len(data.get('data', []))} vLLM models")
    except Exception as e:
        logger.warning(f"Could not connect to vLLM: {e}")

    # (The RTX 5080 rig used to be probed here with its own copy of the block above.
    # It is one of the hosts `ollama_hosts.snapshot()` returns now, so a model that
    # only exists on the rig is reported the same way as a laptop one — and, unlike
    # before, still reported when the rig is asleep.)

    # Fetch from external Ollama (if configured) - runs in parallel with above
    if EXTERNAL_OLLAMA_URL and EXTERNAL_OLLAMA_API_KEY:
        try:
            ext_url = f"{EXTERNAL_OLLAMA_URL}/api/tags"
            ext_headers = {
                "Authorization": f"Bearer {EXTERNAL_OLLAMA_API_KEY}",
                "ngrok-skip-browser-warning": "true",
                "User-Agent": "Harvis-Backend",
            }
            async with httpx.AsyncClient() as client:
                ext_resp = await client.get(ext_url, headers=ext_headers, timeout=10.0)

            if ext_resp.status_code == 200:
                ext_data = ext_resp.json()
                for m in ext_data.get("models", []):
                    model_name = m.get("name")
                    if not any(
                        existing["name"] == model_name for existing in formatted_models
                    ):
                        formatted_models.append(
                            {
                                "name": model_name,
                                "displayName": f"{_pretty_ollama_name(model_name)} (Cloud)",
                                "size": _parse_model_size(m.get("size")),
                                "status": "available",
                                "provider": "ollama-cloud",
                            }
                        )
                        EXTERNAL_MODELS_CACHE.add(model_name)
                logger.info(f"Added external Ollama models")
        except Exception as e:
            logger.warning(f"Could not connect to external Ollama: {e}")

    # Check if user has Moonshot API key configured
    pool = getattr(request.app.state, "pg_pool", None)
    if pool:
        try:
            moonshot_config = await get_user_api_key(pool, current_user.id, "moonshot")
            if moonshot_config and moonshot_config.get("api_key"):
                formatted_models.extend(
                    [
                        {
                            "name": "kimi-k2.5",
                            "displayName": "Kimi K2.5 (Moonshot)",
                            "size": "Cloud",
                            "status": "available",
                            "provider": "moonshot",
                            "description": "Long-context reasoning model via Moonshot AI",
                        },
                        {
                            "name": "kimi-k2",
                            "displayName": "Kimi K2 (Moonshot)",
                            "size": "Cloud",
                            "status": "available",
                            "provider": "moonshot",
                            "description": "Advanced reasoning model via Moonshot AI",
                        },
                    ]
                )
                logger.info("Added Moonshot models for user with API key")
        except Exception as e:
            logger.error(f"Error checking Moonshot API key: {e}")

        # Check if user has NVIDIA API key configured
        try:
            nvidia_config = await get_user_api_key(pool, current_user.id, "nvidia")
            if nvidia_config and nvidia_config.get("api_key"):
                formatted_models.append(
                    {
                        "name": "nvidia-kimi",
                        "displayName": "Kimi K2.5 (NVIDIA NIM)",
                        "size": "Cloud",
                        "status": "available",
                        "provider": "nvidia",
                        "description": "Kimi K2.5 with thinking mode via NVIDIA NIM",
                    }
                )
                logger.info("Added NVIDIA NIM models for user with API key")
        except Exception as e:
            logger.error(f"Error checking NVIDIA API key: {e}")

    # Sort by name
    formatted_models.sort(key=lambda x: x["name"])

    # Cache the result (without user-specific models)
    cache_data = {"models": formatted_models.copy()}
    _set_cached_models(cache_data)

    return {"models": formatted_models}


# ─── Cache Management Endpoint ───────────────────────────────────────────────────
@app.post("/api/models/clear-cache", tags=["models"])
async def clear_models_cache(current_user: UserResponse = Depends(get_current_user)):
    """Clear the models cache (useful after adding/removing models)"""
    global _models_cache
    _models_cache = {"data": None, "timestamp": 0}
    logger.info("Models cache cleared")
    return {"status": "cached", "message": "Models cache cleared"}


# ─── Fallback Models Function ─────────────────────────────────────────────────
def get_fallback_models():
    """Return fallback models when Ollama is down"""
    return {
        "models": [
            {
                "name": "mistral",
                "displayName": "Mistral (Offline)",
                "status": "offline",
                "provider": "ollama",
            },
            {
                "name": "llama3",
                "displayName": "Llama 3 (Offline)",
                "status": "offline",
                "provider": "ollama",
            },
        ]
    }


# ─── Middleware ────────────────────────────────────────────────────────────────

# CORS Middleware must be added before routes
# Origins beyond the built-in local ones. A deployment behind a real hostname
# adds it here rather than editing this list, so no operator's private domain
# ships inside everyone else's trusted-origin set.
#   HARVIS_EXTRA_ORIGINS=https://harvis.example.com,http://harvis.example.com
_EXTRA_ORIGINS = [
    o.strip() for o in os.getenv("HARVIS_EXTRA_ORIGINS", "").split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_EXTRA_ORIGINS + [
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

# ── CSRF guard for the untrusted Repo Runner preview lane ──────────────────────
# get_current_user reads the ambient `access_token` cookie, so a *same-site* origin
# — e.g. a sandbox dev server on another localhost port — could otherwise drive
# credentialed, state-changing API calls as the logged-in user (SameSite=Lax gives
# no protection between two localhost ports). Reject unsafe /api/ requests whose
# Origin is present and is neither same-origin nor on the trusted allowlist.
# Same-origin requests, allowlisted (CORS) origins, and non-browser callers (no
# Origin header, which are Bearer-authed and not a CSRF vector) all pass untouched.
_CSRF_ALLOWED_NETLOCS = {
    *(o.split("://", 1)[-1] for o in _EXTRA_ORIGINS),
    "localhost:9000", "127.0.0.1:9000",
    "localhost:3000", "localhost:3001", "127.0.0.1:3000", "127.0.0.1:3001",
    "frontend:3000", "nginx-proxy:80", "localhost:8000", "127.0.0.1:8000",
}
_CSRF_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def csrf_origin_guard(request: Request, call_next):
    if request.method in _CSRF_UNSAFE_METHODS and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin:
            netloc = origin.split("://", 1)[-1]  # strip scheme → host[:port]
            host = request.headers.get("host", "")
            if netloc != host and netloc not in _CSRF_ALLOWED_NETLOCS:
                logger.warning("CSRF guard blocked %s %s from origin %s (host %s)",
                               request.method, request.url.path, origin, host)
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    {"detail": "Cross-origin request blocked (CSRF protection)."},
                    status_code=403,
                )
    return await call_next(request)


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
app.include_router(terminal_router)
app.include_router(ai_assistant_router)
app.include_router(file_api_router)
app.include_router(user_prefs_router)
app.include_router(proxy_router)
app.include_router(repo_import_router)
app.include_router(ide_ai_router)

# Include notebooks router (from open-notebook merge)
try:
    from notebooks.router import router as notebooks_router
    app.include_router(notebooks_router)
except Exception as e:
    logger.warning(f"Could not load notebooks router: {e}")

# Include open-notebook compatibility facade (/onb-api) — serves the vendored
# open-notebook Next.js frontend (front_end/open-notebook, at /onb) on Harvis data.
try:
    from onb_compat import onb_router
    app.include_router(onb_router)
    logger.info("✅ onb_compat facade mounted at /onb-api")
except Exception as e:
    logger.warning(f"Could not load onb_compat facade: {e}")

# Include open-notebook podcasts facade (/onb-api/podcasts, /onb-api/*-profiles)
try:
    from onb_compat.podcasts import router as onb_podcasts_router
    app.include_router(onb_podcasts_router)
    logger.info("✅ onb_compat podcasts mounted at /onb-api")
except Exception as e:
    logger.warning(f"Could not load onb_compat podcasts facade: {e}")

# Include RAG corpus router
if RAG_CORPUS_AVAILABLE:
    app.include_router(rag_router)

# Include artifacts router
app.include_router(artifact_router)

# Include workspace router (Harvis Workspaces — OpenClaw agent integration)
app.include_router(workspace_router)
# Include workspace terminal router — per-session dockerized shell that lives
# on openclaw-internal so the agent can `curl` it for `exec` calls. Persistent
# named volume per workspace_id (see workspace/terminal_container.py).
app.include_router(workspace_terminal_router)
# Include the Harvis Execution Trace facade (/api/harvis/*) — a clean namespace
# that DELEGATES to workspace_router's store/stream (no new storage of its own).
app.include_router(harvis_trace_router)
# Phase 3: governed user-facing sandbox shell (lane 3) — POST /api/harvis/exec
# routes through authorize_action + emits the full decision/tool_call/
# terminal_output/tool_result trace via workspace_events.
app.include_router(harvis_exec_router)
# Phase E1: NON-BLOCKING background jobs (lane 3) — POST /api/harvis/jobs
# returns a job_id immediately; output streams as terminal_output events on
# the existing /api/harvis/runs/{id}/stream SSE; DELETE kills via pidfile.
# Registry is in-memory (does NOT survive restart — E2 adds persistence).
app.include_router(harvis_jobs_router)
# Phase F: POST /api/harvis/runs/{id}/save-as-skill → a DRAFT (disabled, unaudited) skill.
app.include_router(harvis_skill_extract_router)
# Phases I/H/G: GET /api/harvis/readiness (per-lane, honest) + /api/harvis/providers (unified catalog).
app.include_router(harvis_readiness_router)
# Image-gen v0: POST /api/harvis/image/generate (gated on enable_image_generation + a ready
# ComfyUI/A1111 provider) runs txt2img as a background workspace run; the PNG lands as a
# binary artifact + 'artifact' trace event so the existing Artifacts rail previews it.
app.include_router(harvis_image_router)
# Phase 3: terminal-session REST over the VibeCode PTY — pre-created exec +
# docker exec_resize side-channel. Gated by HARVIS_BUILD_SHELL like the WS.
app.include_router(harvis_terminal_sessions_router)
# Include model proxy (OpenAI-compat endpoint for OpenClaw → Moonshot forwarding)
# OpenClaw calls http://harvis-ai-merged-backend:8000/v1/chat/completions
# so that the Moonshot API key never leaves the backend pod.
app.include_router(model_proxy_router)
# Include GitHub proxy (OpenClaw → backend → GitHub API forwarding).
# Only dulc3/harvis-aidev is allowed; token stays server-side.
app.include_router(github_proxy_router)
# Include RAG proxy (OpenClaw → backend → pgvector semantic search).
# OpenClaw agents call /rag/search to retrieve relevant code/docs chunks
# without needing direct database access or holding DB credentials.
app.include_router(rag_proxy_router)
# Include kubectl proxy — mounted at BOTH prefixes so:
#   • Frontend (via nginx) hits /api/kubectl/pending, /api/kubectl/approve, etc.
#   • OpenClaw pods call /kubectl/exec, /kubectl/health directly (pod-to-pod).
# Both share the same handlers & in-memory approval state.
app.include_router(kubectl_proxy_router, prefix="/api/kubectl")
app.include_router(kubectl_proxy_router, prefix="/kubectl")

# Include workspace repo manager (GitHub repo clone/sync/push for OpenClaw workspace)
app.include_router(repo_manager_router)
# GitHub OAuth for VibeCode (connect → clone → Create-PR). /api/vibecode/github/{start,callback,
# status,disconnect} + the /api/auth/vibecode/github/callback alias. Needs GITHUB_CLIENT_ID/SECRET.
app.include_router(auth_github_router)
app.include_router(auth_github_callback_router)

# Include Maps proxy (Google Maps API endpoints without exposing API keys)
app.include_router(maps_router)

# Include OpenClaw tool proxy (web-fetch + document-save — internal service auth)
app.include_router(openclaw_proxy_router)
app.include_router(browser_proxy_router)

# Include OpenCode LLM proxy (for OpenCode to use Kimi K2.5)
app.include_router(opencode_llm_router)

# Include Discord tools proxy (heartbeat → Discord posting, internal service auth)
app.include_router(discord_proxy_router)

# Include messaging plugin (Phase 1A: gateway-sidecar routes + per-user platform links + audit)
from plugins.messaging.routes import router as messaging_router
app.include_router(messaging_router)

# Phase-storage CRUD routes — JWT-auth via get_current_user_optimized.
# Per-user SOUL.md (Phase 7), memory provider (Phase 4), cron jobs (Phase 6).
from plugins.soul.routes import router as soul_router
from plugins.memory.routes import router as memory_router
from plugins.cron.routes import router as cron_router
from plugins.inference_nodes.routes import router as inference_nodes_router
app.include_router(soul_router)
app.include_router(memory_router)
app.include_router(cron_router)
app.include_router(inference_nodes_router)

# SSH remote-access SCAFFOLD (Phase 7) — flagged OFF: HARVIS_SSH_ENABLED absent/0 (the
# default) → every endpoint 403s; connect/test is additionally a hard 501 stub (no SSH I/O).
from remote.ssh_manager import ssh_router
app.include_router(ssh_router)

# Phase 4 (Execution Core): SSH TARGET REGISTRY — GET /api/harvis/targets lists
# the sandbox container + this user's SSH host profiles (kind ssh, lane 5, NO
# secrets). Read-only; the probe/trust/exec verbs live on ssh_router above.
from remote.targets import targets_router
app.include_router(targets_router)

# Cookbook — hardware-aware model recommendation + download (per-node llmfit serve proxy)
try:
    from cookbook.router import router as cookbook_router
    app.include_router(cookbook_router)
    logger.info("Cookbook router registered at /api/cookbook")
except Exception as e:
    logger.warning(f"Could not load cookbook router: {e}")

# Deep Research — agentic multi-step research + visual reports (Odysseus port)
try:
    from deep_research.router import router as deep_research_router
    app.include_router(deep_research_router)
    logger.info("Deep Research router registered at /api/research")
except Exception as e:
    logger.warning(f"Could not load deep_research router: {e}")

# First-run setup wizard probes (status/verify/test-model/preferences/complete)
app.include_router(
    create_setup_router(
        get_current_user=get_current_user,
        require_admin=require_admin,
    )
)
logger.info("Setup flow router registered at /api/setup/*")

# ─── Device & models -----------------------------------------------------------
device = 0 if torch.cuda.is_available() else -1
logger.info("Using device: %s", "cuda" if device == 0 else "cpu")


# ─── Config --------------------------------------------------------------------

# The canonical provider base URL, resolved once at the top of this module
# (HARVIS_LLM_BASE_URL → OLLAMA_URL → http://host.docker.internal:11434).
# In the merged k8s pod OLLAMA_URL points at vLLM on :8001/v1 and that still
# flows through here unchanged — the shim only supplies the default.
LOCAL_OLLAMA_URL = HARVIS_LLM_BASE_URL
# Secondary probe slots for host-run OpenAI-compatible servers. localhost here
# would be the CONTAINER's loopback, which can never reach a host-run server —
# host.docker.internal is the host (extra_hosts maps it to the gateway).
VLLM_URL = os.getenv("VLLM_URL", "http://host.docker.internal:8001/v1")  # vLLM
LLAMA_URL = os.getenv(
    "LLAMA_URL", "http://host.docker.internal:8080/v1"
)  # llama-server — devstral long-ctx
API_KEY = os.getenv("OLLAMA_API_KEY", "key")
# No model name is hardcoded here. "qwen3.5-27b" used to be, and that tag exists on
# nobody's machine — including this one — so every request that fell back to the default
# asked the provider for a model it did not have. The default is now whatever the
# deployment actually serves, discovered from /api/tags at first use.
#
#   HARVIS_DEFAULT_MODEL   pin one explicitly (any provider, any tag)
#   unset                  first model the configured provider reports
#   no provider yet        "" — the caller must name a model, and the error says so
DEFAULT_MODEL = os.getenv("HARVIS_DEFAULT_MODEL", "").strip()
_RESOLVED_DEFAULT_MODEL: Optional[str] = DEFAULT_MODEL or None
_DEFAULT_MODEL_PROBED = False


def resolve_default_model() -> str:
    """The model to use when the caller named none.

    Resolution order: explicit pin, then the provider's own first tag, then "".
    Probed once and cached; a deployment that pulls its first model after boot picks it
    up on the next cache clear (``/api/models/clear-cache``), not on every request.
    """
    global _RESOLVED_DEFAULT_MODEL, _DEFAULT_MODEL_PROBED
    if _RESOLVED_DEFAULT_MODEL:
        return _RESOLVED_DEFAULT_MODEL
    if _DEFAULT_MODEL_PROBED:
        return ""
    _DEFAULT_MODEL_PROBED = True
    import httpx  # imported per-function throughout this module, not at top level

    # Whatever the local cache already learned beats an HTTP round-trip.
    if LOCAL_OLLAMA_MODELS_CACHE:
        _RESOLVED_DEFAULT_MODEL = sorted(LOCAL_OLLAMA_MODELS_CACHE)[0]
        return _RESOLVED_DEFAULT_MODEL
    base = HARVIS_LLM_BASE_URL[:-3] if HARVIS_LLM_BASE_URL.endswith("/v1") else HARVIS_LLM_BASE_URL
    for url, pick in (
        (f"{base}/api/tags", lambda d: [m.get("name") for m in (d.get("models") or [])]),
        (f"{base}/v1/models", lambda d: [m.get("id") for m in (d.get("data") or [])]),
    ):
        try:
            with httpx.Client(timeout=httpx.Timeout(3.0)) as client:
                r = client.get(url)
            if r.status_code >= 400:
                continue
            names = [n for n in pick(r.json()) if n]
            if names:
                _RESOLVED_DEFAULT_MODEL = names[0]
                logger.info("default model resolved from %s: %s", url, _RESOLVED_DEFAULT_MODEL)
                return _RESOLVED_DEFAULT_MODEL
        except Exception:
            continue
    logger.warning(
        "No default model: the provider at %s reported none. Requests must name a model, "
        "or set HARVIS_DEFAULT_MODEL.", base,
    )
    return ""


def _default_model_field() -> str:
    """Pydantic default_factory — runs per request, so it can't bake in a boot-time guess."""
    return resolve_default_model()

# External Ollama endpoint (for large models hosted elsewhere)
# NOTE: Set to empty string by default - external routing only when explicitly configured
EXTERNAL_OLLAMA_URL = os.getenv("EXTERNAL_OLLAMA_URL", "")
EXTERNAL_OLLAMA_API_KEY = os.getenv("EXTERNAL_OLLAMA_API_KEY", "")

# Models cache for routing decisions
# Only models discovered from the external endpoint will be added here
EXTERNAL_MODELS_CACHE = set()

# Models discovered from the native Ollama API of the configured provider.
# Used to route chat requests to the native Ollama API instead of vLLM/llama-server
LOCAL_OLLAMA_MODELS_CACHE = set()
# OLLAMA_NATIVE_URL still wins when set (deploys where OLLAMA_URL points at a
# vLLM /v1 endpoint and native Ollama lives elsewhere). Otherwise fall back to
# the canonical base URL — the old `http://ollama:11434` default named a compose
# service that no longer exists and could never resolve.
LOCAL_OLLAMA_BASE_URL = (
    os.getenv("OLLAMA_NATIVE_URL") or HARVIS_LLM_BASE_URL
).rstrip("/")

# ─── Model List Cache (for /api/models endpoint) ─────────────────────────────────
import time

_models_cache = {"data": None, "timestamp": 0}
_MODELS_CACHE_TTL = 60  # Cache models list for 60 seconds


def _get_cached_models():
    """Return cached models if still valid, otherwise None"""
    if (
        _models_cache["data"]
        and (time.time() - _models_cache["timestamp"]) < _MODELS_CACHE_TTL
    ):
        return _models_cache["data"]
    return None


def _set_cached_models(models):
    """Cache the models list"""
    _models_cache["data"] = models
    _models_cache["timestamp"] = time.time()


def _parse_model_size(size_value):
    """Parse model size, handling both int and string types"""
    try:
        size = int(size_value) if isinstance(size_value, str) else size_value
        if size:
            return f"{size / (1024**3):.1f}GB"
    except (ValueError, TypeError, ZeroDivisionError):
        pass
    return "Unknown"


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
    is_local_ollama_model = model_name in LOCAL_OLLAMA_MODELS_CACHE

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

    # Route to local Ollama Docker service for models discovered from it
    if is_local_ollama_model:
        ollama_base = LOCAL_OLLAMA_BASE_URL
        if "/v1" in ollama_base:
            ollama_base = ollama_base.replace("/v1", "")
        url = f"{ollama_base}{endpoint}"
        try:
            logger.info("🏠 Using local Ollama (Docker) for %s: %s (stream=%s)", model_name, url, stream)
            response = requests.post(
                url, json=payload, timeout=timeout, stream=stream
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

    # Use user settings if provided, otherwise use global defaults (vLLM/llama-server)
    if user_settings:
        local_url = user_settings.get("local_url") or LOCAL_OLLAMA_URL
    else:
        local_url = LOCAL_OLLAMA_URL

    # Try vLLM/llama-server
    try:
        logger.info("🏠 Using vLLM/llama-server: %s", local_url)
        response = requests.post(
            f"{local_url}{endpoint}", json=payload, timeout=timeout, stream=stream
        )
        if response.status_code == 200:
            logger.info("✅ vLLM/llama-server request successful")
            return response
        else:
            logger.error("❌ vLLM/llama-server returned status %s", response.status_code)
            response.raise_for_status()
    except Exception as e:
        logger.error("❌ vLLM/llama-server request failed: %s", e)
        raise


# ─── SSE Heartbeat Constants ──────────────────────────────────────────────────
HEARTBEAT_INTERVAL = 10  # Send heartbeat every 10 seconds to keep connection alive
MAX_RESPONSE_SIZE = int(
    os.getenv("MAX_RESPONSE_SIZE", "100000")
)  # Default 100k chars (~20k words)


async def stream_ollama_chunks(endpoint, payload, timeout=3600):
    """
    Stream chunks from the inference backend (local Ollama, vLLM, or llama-server).

    Routing priority:
    1. External Ollama (cloud-hosted models in EXTERNAL_MODELS_CACHE)
    2. Local Ollama Docker service (models in LOCAL_OLLAMA_MODELS_CACHE)
    3. llama-server / vLLM (everything else)

    Yields JSON-encoded bytes in Ollama NDJSON format so existing consumers
    remain unchanged:  {"message": {"content": "..."}, "done": false}
    """
    import httpx

    # Routing logic
    model_name = payload.get("model", "")
    is_external_model = model_name in EXTERNAL_MODELS_CACHE
    is_local_ollama_model = model_name in LOCAL_OLLAMA_MODELS_CACHE

    # ── 1. External Ollama (cloud-hosted models) ──────────────────────────────────
    if is_external_model and EXTERNAL_OLLAMA_URL and EXTERNAL_OLLAMA_API_KEY:
        url = f"{EXTERNAL_OLLAMA_URL}{endpoint}"
        headers = {
            "Authorization": f"Bearer {EXTERNAL_OLLAMA_API_KEY}",
            "ngrok-skip-browser-warning": "true",
            "User-Agent": "Harvis-Backend",
        }
        logger.info(f"🌐 Using external Ollama for {model_name}: {url}")
        # External Ollama uses Ollama NDJSON format — stream raw lines as before
        try:
            timeout_config = httpx.Timeout(timeout, connect=60.0)
            async with httpx.AsyncClient(timeout=timeout_config) as client:
                async with client.stream(
                    "POST", url, json=payload, headers=headers
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        raise Exception(
                            f"External Ollama error {response.status_code}: {error_text.decode('utf-8', errors='ignore')[:200]}"
                        )
                    async for line in response.aiter_lines():
                        if line:
                            yield line.encode("utf-8")
        except httpx.ReadTimeout:
            logger.error(f"❌ External Ollama read timeout after {timeout}s")
            raise Exception("Ollama generation timed out")
        except Exception as e:
            logger.error(f"❌ External Ollama stream error: {e}")
            raise
        return

    # ── 2. Local Ollama Docker service (native Ollama API) ────────────────────────
    if is_local_ollama_model:
        # Strip /v1 suffix if present — Ollama uses its own /api/chat endpoint
        ollama_base = LOCAL_OLLAMA_BASE_URL
        if "/v1" in ollama_base:
            ollama_base = ollama_base.replace("/v1", "")
        url = f"{ollama_base}{endpoint}"
        logger.info(f"🏠 Using local Ollama for {model_name}: {url}")
        try:
            timeout_config = httpx.Timeout(timeout, connect=60.0)
            async with httpx.AsyncClient(timeout=timeout_config) as client:
                async with client.stream(
                    "POST", url, json=payload
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        raise Exception(
                            f"Local Ollama error {response.status_code}: {error_text.decode('utf-8', errors='ignore')[:200]}"
                        )
                    async for line in response.aiter_lines():
                        if line:
                            yield line.encode("utf-8")
        except httpx.ReadTimeout:
            logger.error(f"❌ Local Ollama read timeout after {timeout}s")
            raise Exception("Local Ollama generation timed out")
        except Exception as e:
            logger.error(f"❌ Local Ollama stream error: {e}")
            raise
        return

    # ── 3. Local backend: vLLM or llama-server (OpenAI SSE format) ────────────────
    # Translate Ollama /api/chat payload → OpenAI /v1/chat/completions payload
    openai_payload = {
        "model": model_name or resolve_default_model(),
        "messages": payload.get("messages", []),
        "stream": True,
        "temperature": payload.get("options", {}).get("temperature", 0.7),
    }
    if "max_tokens" in payload.get("options", {}):
        openai_payload["max_tokens"] = payload["options"]["max_tokens"]

    # Use vLLM for default; llama-server for specific models (long-context or GGUF)
    llama_server_models = ["devstral-small-2:24b", "qwen3:8b", "qwen3-8b"]
    if (
        model_name in llama_server_models
        or model_name.startswith("qwen3")
        or model_name.startswith("qwen2")
    ):
        base_url = LLAMA_URL
        logger.info(f"🏠 Using llama-server for {model_name}: {base_url}")
    else:
        base_url = VLLM_URL
        logger.info(f"🏠 Using vLLM (fast): {base_url}")

    url = f"{base_url}/chat/completions"
    headers = {"Content-Type": "application/json"}

    try:
        timeout_config = httpx.Timeout(timeout, connect=60.0)
        async with httpx.AsyncClient(timeout=timeout_config) as client:
            async with client.stream(
                "POST", url, json=openai_payload, headers=headers
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise Exception(
                        f"Inference backend error {response.status_code}: {error_text.decode('utf-8', errors='ignore')[:200]}"
                    )

                # Parse OpenAI SSE and re-emit in Ollama NDJSON format
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            yield json.dumps(
                                {"message": {"content": ""}, "done": True}
                            ).encode("utf-8")
                            break
                        try:
                            chunk_json = json.loads(data_str)
                            content_chunk = (
                                chunk_json.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            ) or ""
                            ollama_chunk = {
                                "message": {"content": content_chunk},
                                "done": False,
                            }
                            yield json.dumps(ollama_chunk).encode("utf-8")
                        except (json.JSONDecodeError, IndexError):
                            continue

    except httpx.ReadTimeout:
        logger.error(f"❌ Inference backend read timeout after {timeout}s")
        raise Exception("Inference backend generation timed out")
    except Exception as e:
        logger.error(f"❌ Inference backend stream error: {e}")
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
        return transcribe_audio(audio_path)

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
    tts_engine: str = "qwen",
):
    """
    Run TTS in a background thread with heartbeats.

    Args:
        text: Text to synthesize
        audio_prompt: Voice prompt for cloning (Chatterbox only)
        exaggeration: Voice expressiveness (Chatterbox only)
        temperature: Generation temperature
        cfg_weight: CFG weight (Chatterbox only)
        auto_unload: Unload TTS after generation
        tts_engine: "qwen" or "chatterbox" TTS engine selection
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
            tts_engine=tts_engine,
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
    model: str = Field(default_factory=_default_model_field)
    session_id: Optional[str] = None  # Chat session ID for history persistence
    audio_prompt: Optional[str] = None  # overrides HARVIS_VOICE_PATH if provided
    attachments: Optional[List[Dict[str, Any]]] = None  # List of file attachments
    exaggeration: float = 0.5
    temperature: float = 0.5  # Lower temp = more stable TTS output
    cfg_weight: float = 2.0  # Higher cfg = follows text more closely
    low_vram: bool = False
    text_only: bool = False
    tts_engine: str = "qwen"  # "qwen" or "chatterbox" TTS engine selection
    thinking_mode: bool = (
        False  # When True, use chain-of-thought reasoning (slower but deeper)
    )


class ResearchChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []
    model: str = Field(default_factory=_default_model_field)
    session_id: Optional[str] = None  # Chat session ID for history persistence
    enableWebSearch: bool = True
    live_web: bool = False  # When True, route research through OpenClaw with unrestricted web access
    audio_prompt: Optional[str] = None  # overrides HARVIS_VOICE_PATH if provided
    exaggeration: float = 0.5
    temperature: float = 0.5  # Lower temp = more stable TTS output
    cfg_weight: float = 2.0  # Higher cfg = follows text more closely
    tts_engine: str = "qwen"  # "qwen" or "chatterbox" TTS engine selection


class ScreenAnalysisRequest(BaseModel):
    image: str  # base-64 image (data-URI or raw)


class SynthesizeSpeechRequest(BaseModel):
    text: str
    audio_prompt: Optional[str] = None
    exaggeration: float = 0.5
    temperature: float = 0.8
    cfg_weight: float = 0.5
    tts_engine: str = "qwen"  # "qwen" or "chatterbox" TTS engine selection


# VibeCommandRequest moved to vibecoding.commands


class AnalyzeAndRespondRequest(BaseModel):
    image: str  # base-64 image (data-URI or raw)
    model: str = Field(default_factory=_default_model_field)
    system_prompt: Optional[str] = None


class ScreenAnalysisWithTTSRequest(BaseModel):
    image: str  # base-64 image (data-URI or raw)
    model: str = Field(default_factory=_default_model_field)
    system_prompt: Optional[str] = None
    audio_prompt: Optional[str] = None
    exaggeration: float = 0.5
    temperature: float = 0.8
    cfg_weight: float = 0.5


class VisionChatRequest(BaseModel):
    """Request model for Ollama vision chat (llava, moondream, etc.)"""

    message: str
    images: List[str] = []  # List of base64 images (data-URI or raw)
    history: List[Dict[str, Any]] = []
    model: str = "llava"  # Default to llava, user can select any VL model
    session_id: Optional[str] = None
    low_vram: bool = False
    text_only: bool = False
    # NEW: Support for document files (PDF, DOCX) that will be converted to images
    files: Optional[List[Dict[str, Any]]] = None  # [{name, data, mimeType}]


# VibeCodingRequest moved to vibecoding.commands


class VoiceTranscribeRequest(BaseModel):
    model: str = Field(default_factory=_default_model_field)


class RunCommandRequest(BaseModel):
    command: str


class SaveFileRequest(BaseModel):
    filename: str
    content: str


# ─── API Key Management Models ------------------------------------------------
class ApiKeyRequest(BaseModel):
    provider_name: str
    api_key: str
    api_url: Optional[str] = None
    is_active: bool = True


class ApiKeyResponse(BaseModel):
    id: int
    provider_name: str
    api_url: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ApiKeyUpdateRequest(BaseModel):
    api_key: Optional[str] = None
    api_url: Optional[str] = None
    is_active: Optional[bool] = None




# ─── Harvis Claw LLM Config Models ───────────────────────────────────────────

class OpenClawConfigRequest(BaseModel):
    provider_url: str
    api_key: Optional[str] = None
    model_id: str
    provider_type: str = "openai"  # 'openai', 'ollama', 'anthropic'


class OpenClawConfigResponse(BaseModel):
    id: int
    provider_url: str
    model_id: str
    provider_type: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

# ─── Harvis Claw LLM Config Models ───────────────────────────────────────────
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


@app.get("/health", tags=["health"])
async def health_check():
    """Lightweight health check for K8s liveness probe - responds immediately"""
    return {"status": "healthy", "timestamp": time.time()}


@app.get("/api/health/services", tags=["health"])
async def health_services():
    """Check reachability of backend services (model provider, pgsql, openclaw,
    browser-runner, tts-service).

    The model provider is NOT a compose service any more (plug-and-play: the
    user brings their own server, reached via HARVIS_LLM_BASE_URL). It is
    reported under the key "model_provider" with its own states so a correct
    no-provider install does not read as degraded:
      • up              — provider answered
      • not_configured  — base URL is still the default guess and nothing
                          answered there; healthy, just no provider yet
      • down            — an explicitly configured provider is unreachable;
                          this DOES degrade overall
    """
    results: dict = {}
    overall = "healthy"

    async def _check(name: str, url: str, timeout: float = 5.0):
        nonlocal overall
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
                r = await client.get(url)
            if r.status_code < 400:
                results[name] = {"status": "up", "code": r.status_code}
            else:
                # It answered, so it IS installed — an error code is a real fault
                # even for an optional service.
                results[name] = {"status": "degraded", "code": r.status_code}
                overall = "degraded"
        except Exception as exc:
            # Unreachable. Whether that is a FAULT depends on whether the operator
            # asked for this capability: profile-gated services are absent from a
            # correct default install, and calling that install degraded teaches
            # people to ignore this page. We still probe first, so a service that
            # is running despite a stale/absent HARVIS_ENABLED_PROFILES is
            # reported up rather than written off as missing.
            if not service_expected(name):
                results[name] = {
                    "status": "not_installed",
                    "reason": f"compose profile '{_SERVICE_PROFILE[name]}' is not enabled",
                }
            else:
                results[name] = {"status": "down", "error": str(exc)[:200]}
                overall = "degraded"

    # Model provider — the user's own server, not a compose service. Use the
    # raw Ollama API, not the vLLM-style /v1 path.
    _ollama_base = HARVIS_LLM_BASE_URL
    # Strip /v1 suffix if present — /api/tags lives on the root Ollama port
    if _ollama_base.endswith("/v1"):
        _ollama_base = _ollama_base[:-3]

    async def _check_model_provider():
        nonlocal overall
        url = f"{_ollama_base}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                r = await client.get(url)
            if r.status_code < 400:
                results["model_provider"] = {
                    "status": "up", "code": r.status_code, "url": _ollama_base,
                }
            else:
                results["model_provider"] = {
                    "status": "degraded", "code": r.status_code, "url": _ollama_base,
                }
                overall = "degraded"
        except Exception as exc:
            if LLM_PROVIDER_EXPLICITLY_CONFIGURED:
                # The operator pointed us at a server and it does not answer —
                # a real fault.
                results["model_provider"] = {
                    "status": "down", "url": _ollama_base,
                    "error": str(exc)[:200],
                }
                overall = "degraded"
            else:
                # Supported no-provider install: nothing configured, nothing on
                # the conventional host port. Healthy — just no models yet.
                results["model_provider"] = {
                    "status": "not_configured", "url": _ollama_base,
                    "reason": (
                        "no model provider configured — set HARVIS_LLM_BASE_URL "
                        "or start a server on the host's port 11434"
                    ),
                }

    # OpenClaw — HTTP health endpoint (WS gateway also serves /health over HTTP)
    _openclaw_ws = os.getenv("OPENCLAW_URL", "ws://openclaw:18789")
    _openclaw_http = _openclaw_ws.replace("ws://", "http://").replace("wss://", "https://")

    _tts_base = os.getenv("TTS_SERVICE_URL", "http://tts-service:8001").rstrip("/")

    await asyncio.gather(
        _check_model_provider(),
        _check("openclaw", f"{_openclaw_http}/health"),
        _check("browser-runner", "http://browser-runner:8765/health", timeout=8.0),
        _check("tts-service", f"{_tts_base}/health"),
    )

    # Database check — use the existing connection pool (not HTTP)
    try:
        pool = getattr(app.state, "pg_pool", None)
        if pool:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            results["database"] = {"status": "up"}
        else:
            results["database"] = {"status": "unknown", "error": "no connection pool"}
            overall = "degraded"
    except Exception as exc:
        results["database"] = {"status": "down", "error": str(exc)[:200]}
        overall = "degraded"

    return {
        "status": overall,
        "timestamp": time.time(),
        "services": results,
    }





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
    setup_code = app_request.headers.get("x-setup-code")

    if pool:
        async with pool.acquire() as conn:
            return await _signup_with_connection(request, conn, setup_code=setup_code)
    else:
        conn = await asyncpg.connect(DATABASE_URL, timeout=10)
        try:
            return await _signup_with_connection(request, conn, setup_code=setup_code)
        finally:
            await conn.close()


# Serializes concurrent first-signups so exactly one can claim admin.
_FIRST_SIGNUP_LOCK_KEY = 0x48415256  # "HARV"


async def _signup_enabled(conn) -> bool:
    # Default ON, and it must stay in lockstep with owui_compat/config.py's
    # "enable_signup" — that flag is what draws the "Don't have an account?
    # Sign up" link, so a mismatch either hides a working signup or shows a
    # link that 403s. The first signup claims admin; every later one creates an
    # ordinary user. Close signup for an internet-facing instance — that is the
    # flag that matters, not HARVIS_SETUP_CODE.
    #
    # The answer now comes from owui_compat.admin_config, which reads the value
    # the admin last set in Settings → General and falls back to
    # HARVIS_OWUI_ENABLE_SIGNUP when they never touched it. Both the switch and
    # the .env var therefore work, and /api/config resolves the same way, so
    # the form and the gate cannot disagree.
    from owui_compat.admin_config import signup_enabled

    return await signup_enabled(conn)


async def _signup_with_connection(request: SignupRequest, conn, setup_code: str | None = None):
    try:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1)", _FIRST_SIGNUP_LOCK_KEY
            )
            user_count = await conn.fetchval("SELECT COUNT(*) FROM users")

            if user_count == 0:
                # First signup claims the instance and becomes admin. Open by
                # default, same as OpenWebUI and Jellyfin: a fresh install
                # should be usable without digging a code out of .env, and on
                # a laptop there is nobody to race you to it.
                #
                # An operator who leaves an UNCLAIMED instance reachable from
                # an untrusted network (VPS, shared LAN) closes that window by
                # setting HARVIS_SETUP_CODE — present and non-empty turns the
                # claim back into a gated one. build_config() mirrors this as
                # features.setup_code_required so the signup form knows to ask;
                # the two must stay in lockstep or the form asks for a code
                # nothing checks, or omits one the server demands.
                expected = os.getenv("HARVIS_SETUP_CODE", "").strip()
                if expected and not (
                    setup_code
                    and hmac.compare_digest(expected.encode(), setup_code.encode())
                ):
                    raise HTTPException(
                        status_code=403,
                        detail="First signup requires a valid setup code (X-Setup-Code header)",
                    )
            elif not await _signup_enabled(conn):
                raise HTTPException(
                    status_code=403,
                    detail="Signup is disabled on this instance",
                )

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

            if user_count == 0:
                await conn.execute(
                    """
                    INSERT INTO instance_settings (key, value)
                    VALUES ('admin_user_id', $1)
                    ON CONFLICT (key) DO NOTHING
                    """,
                    str(user_id),
                )
                from owui_compat import translate as _owui_translate
                _owui_translate.add_persisted_admin_id(int(user_id))
                logger.info(f"🔐 Instance claimed: user {user_id} is the admin")

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
            # HARVIS_COOKIE_SECURE=true behind HTTPS; leave false on localhost/LAN HTTP.
            secure=os.getenv("HARVIS_COOKIE_SECURE", "").strip().lower()
            in {"1", "true", "yes", "on"},
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
async def get_authentication_stats(
    current_user: UserResponse = Depends(get_current_user),
):
    """Get authentication performance statistics"""
    return get_auth_stats()


# ─── OpenWebUI-compatibility facade ───────────────────────────────────────────
# Lets the forked OpenWebUI frontend run against this backend. Registered HERE
# (after the auth helpers above are defined) so the facade can reuse them via
# dependency injection without import cycles. All routes are additive EXCEPT
# GET /api/models — Harvis's native `{models:[...]}` shape now lives at
# /api/models/native; the facade serves /api/models in OWUI's `{data:[...]}` shape.
from owui_compat import OwuiDeps, create_owui_router

app.include_router(
    create_owui_router(
        OwuiDeps(
            get_current_user=get_current_user,
            list_models=list_models,
            signup_with_connection=_signup_with_connection,
            signup_request_cls=SignupRequest,
            verify_password=verify_password,
            create_access_token=create_access_token,
            access_token_expire_minutes=ACCESS_TOKEN_EXPIRE_MINUTES,
            secret_key=SECRET_KEY,
            algorithm=ALGORITHM,
        )
    )
)


# ─── API Key Management Endpoints ─────────────────────────────────────────────
@app.get("/api/user/api-keys", response_model=List[ApiKeyResponse], tags=["api-keys"])
async def get_user_api_keys(
    request: Request, current_user: UserResponse = Depends(get_current_user)
):
    """Get all API keys for the current user (without the actual key values)"""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, provider_name, api_url, is_active, created_at, updated_at
            FROM user_api_keys
            WHERE user_id = $1
            ORDER BY provider_name
            """,
            current_user.id,
        )

        return [
            ApiKeyResponse(
                id=row["id"],
                provider_name=row["provider_name"],
                api_url=row["api_url"],
                is_active=row["is_active"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]


@app.post("/api/user/api-keys", response_model=ApiKeyResponse, tags=["api-keys"])
async def create_or_update_api_key(
    request: Request,
    api_key_data: ApiKeyRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """Create or update an API key for a provider"""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    # Never log any part of a credential. This previously logged the first 8 and last 4
    # characters at INFO on every save, which put a usable fragment of the key into the
    # container log — where it persists long after the key is rotated.
    received_key = api_key_data.api_key or ""
    provider = (api_key_data.provider_name or "").strip()
    api_url = api_key_data.api_url
    logger.info("API SAVE: received key for provider=%s (%s)", provider, _key_fingerprint(received_key))

    # Moonshot/Kimi: prove the key works BEFORE storing it, and record WHICH of Moonshot's
    # two platforms accepted it. Storing unverified meant the first sign of a bad key was a
    # 401 in the middle of a build, with nothing pointing at the real cause — usually a key
    # from the other console. Verified-at-save is the same contract Codex and Claude Code
    # already use (owui_compat/engine_auth.py::_verify_credential).
    if provider in ("moonshot", "kimi") and received_key:
        from moonshot_api import verify_moonshot_key

        ok, working_url, err = await verify_moonshot_key(received_key, api_url)
        if not ok:
            raise HTTPException(status_code=400, detail=err)
        api_url = working_url

    # Encrypt the API key
    encrypted_key = encrypt_api_key(api_key_data.api_key)

    async with pool.acquire() as conn:
        # Check if there's already an entry for this provider
        existing = await conn.fetchrow(
            """
            SELECT id FROM user_api_keys
            WHERE user_id = $1 AND provider_name = $2
            """,
            current_user.id,
            api_key_data.provider_name,
        )

        if existing:
            # Update existing entry
            row = await conn.fetchrow(
                """
                UPDATE user_api_keys
                SET api_key_encrypted = $3, api_url = $4, is_active = $5, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = $1 AND provider_name = $2
                RETURNING id, provider_name, api_url, is_active, created_at, updated_at
                """,
                current_user.id,
                api_key_data.provider_name,
                encrypted_key,
                api_url,
                api_key_data.is_active,
            )
        else:
            # Create new entry
            row = await conn.fetchrow(
                """
                INSERT INTO user_api_keys (user_id, provider_name, api_key_encrypted, api_url, is_active)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id, provider_name, api_url, is_active, created_at, updated_at
                """,
                current_user.id,
                api_key_data.provider_name,
                encrypted_key,
                api_url,
                api_key_data.is_active,
            )

        return ApiKeyResponse(
            id=row["id"],
            provider_name=row["provider_name"],
            api_url=row["api_url"],
            is_active=row["is_active"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@app.delete("/api/user/api-keys/{provider_name}", tags=["api-keys"])
async def delete_api_key(
    provider_name: str,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
):
    """Delete an API key for a provider"""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM user_api_keys
            WHERE user_id = $1 AND provider_name = $2
            """,
            current_user.id,
            provider_name,
        )

        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="API key not found")

        return {"message": f"API key for {provider_name} deleted successfully"}


@app.get(
    "/api/user/api-keys/{provider_name}",
    response_model=ApiKeyResponse,
    tags=["api-keys"],
)
async def get_api_key_by_provider(
    provider_name: str,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
):
    """Get a specific API key by provider name (without the actual key value)"""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, provider_name, api_url, is_active, created_at, updated_at
            FROM user_api_keys
            WHERE user_id = $1 AND provider_name = $2
            """,
            current_user.id,
            provider_name,
        )

        if not row:
            raise HTTPException(status_code=404, detail="API key not found")

        return ApiKeyResponse(
            id=row["id"],
            provider_name=row["provider_name"],
            api_url=row["api_url"],
            is_active=row["is_active"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# ─── Harvis Claw LLM Config Endpoints ─────────────────────────────────────

@app.get("/api/user/openclaw-config", response_model=OpenClawConfigResponse, tags=["openclaw"])
async def get_openclaw_config(
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
):
    """Get the current user's Harvis Claw LLM configuration"""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, provider_url, model_id, provider_type, is_active, created_at, updated_at
            FROM openclaw_llm_config
            WHERE user_id = $1 AND is_active = TRUE
            """,
            current_user.id,
        )

        if not row:
            # Return default config for new users
            return OpenClawConfigResponse(
                id=0,
                provider_url=HARVIS_LLM_BASE_URL,
                model_id="qwen2.5-coder:32b",
                provider_type="ollama",
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )

        return OpenClawConfigResponse(
            id=row["id"],
            provider_url=row["provider_url"],
            model_id=row["model_id"],
            provider_type=row["provider_type"],
            is_active=row["is_active"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@app.post("/api/user/openclaw-config", response_model=OpenClawConfigResponse, tags=["openclaw"])
async def save_openclaw_config(
    request: Request,
    config: OpenClawConfigRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """Save the user's Harvis Claw LLM configuration"""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    # Encrypt the API key if provided
    encrypted_key = None
    if config.api_key:
        encrypted_key = encrypt_api_key(config.api_key)

    async with pool.acquire() as conn:
        # Upsert the config
        row = await conn.fetchrow(
            """
            INSERT INTO openclaw_llm_config (user_id, provider_url, api_key_encrypted, model_id, provider_type, is_active)
            VALUES ($1, $2, $3, $4, $5, TRUE)
            ON CONFLICT (user_id) DO UPDATE SET
                provider_url = EXCLUDED.provider_url,
                api_key_encrypted = EXCLUDED.api_key_encrypted,
                model_id = EXCLUDED.model_id,
                provider_type = EXCLUDED.provider_type,
                is_active = TRUE,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, provider_url, model_id, provider_type, is_active, created_at, updated_at
            """,
            current_user.id,
            config.provider_url,
            encrypted_key,
            config.model_id,
            config.provider_type,
        )

        return OpenClawConfigResponse(
            id=row["id"],
            provider_url=row["provider_url"],
            model_id=row["model_id"],
            provider_type=row["provider_type"],
            is_active=row["is_active"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@app.delete("/api/user/openclaw-config", tags=["openclaw"])
async def delete_openclaw_config(
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
):
    """Reset Harvis Claw config to default (Ollama)"""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    async with pool.acquire() as conn:
        await conn.execute(
            """
            DELETE FROM openclaw_llm_config
            WHERE user_id = $1
            """,
            current_user.id,
        )

        return {"message": "OpenClaw config reset to default (Ollama)"}


# ── Web Search Tool Detection ───────────────────────────────────────────────────
    """
    Only trigger web research when the user explicitly asks for a search.
    Harvis can also trigger search by emitting <web_search>query</web_search> in its response.
    Freshness/recommendation keywords no longer auto-trigger — avoids false positives
    on messages like "update the repo" or "what's the best way to refactor this".
    """
    msg_lower = message.lower()

    # Only trigger on unambiguous explicit search requests
    explicit_research = [
        "search for",
        "look up",
        "find sources",
        "web search",
        "check online",
        "search the web",
        "google that",
        "search online",
    ]

    for keyword in explicit_research:
        if keyword in msg_lower:
            logger.info(f"🔍 Search triggered by explicit keyword: '{keyword}'")
            return True

    return False


# ── Local RAG Context Helper ────────────────────────────────────────────────────
async def get_local_rag_context(query: str, max_length: int = None) -> str:
    """
    Retrieve relevant context from the local RAG corpus.
    Returns formatted context string or empty string if unavailable.

    Uses RAG_CONFIG for default values:
    - default_k: Number of results to retrieve (default: 5)
    - max_context_length: Max chars for context (default: 4000)
    """
    # Use RAG_CONFIG defaults if not specified
    if max_length is None:
        max_length = RAG_CONFIG["max_context_length"]

    logger.info(f"🔍 RAG: Starting context retrieval for query: '{query[:100]}...'")

    if local_rag_retriever is None:
        logger.error("❌ RAG: local_rag_retriever is None - not initialized!")
        return ""

    try:
        k = RAG_CONFIG["default_k"]
        logger.info(
            f"🔍 RAG: Retriever initialized, querying with k={k}, max_length={max_length}"
        )

        # First, let's check if we can retrieve raw results (uses retriever's default_k)
        raw_results = await local_rag_retriever.retrieve(query)
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

        # Now get formatted context (uses retriever's default_k)
        context = await local_rag_retriever.get_context_string(
            query=query, max_length=max_length
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


import re as _re

# Auto-research trigger — intentionally narrow. Generic conversational openers like
# "what is", "tell me about", "find out", "how does", etc. are NOT triggers because
# they appear constantly in normal chat (including in user-attached file analysis
# prompts where research would silently steal the request and never display output).
# To force research, the user can toggle research mode in the UI, or use one of the
# explicit phrases below.
_RESEARCH_PATTERNS = _re.compile(
    r"(?i)\b("
    r"search\s+(the\s+web|online)|"
    r"google\s+(it|this|that|for)|"
    r"look\s+(it|this|that)\s+up\s+online|"
    r"research\s+(this|that|for\s+me|the|on)|"
    r"latest\s+news\s+(on|about|in)|"
    r"recent\s+(news|developments|articles)\s+(on|about)|"
    r"web\s+search\s+(for|on)"
    r")\b"
)

def should_auto_research(message: str) -> bool:
    """Return True when the message looks like a research/factual query."""
    if not message or len(message) < 10:
        return False
    if message.strip().startswith("/"):
        return False
    return bool(_RESEARCH_PATTERNS.search(message))


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

            # ── 1.5 Workspace detection (high → auto-launch, medium → suggestion) ────────
            try:
                from workspace.task_detector import detect_workspace_task
                detector_history = (req.history or []) + [
                    {"role": "user", "content": current_message_content}
                ]
                suggestion = await detect_workspace_task(detector_history)
            except Exception as det_exc:
                logger.warning("Workspace detection failed, falling through: %s", det_exc)
                suggestion = None

            force_workspace = bool(getattr(req, "force_workspace", False))

            if suggestion is not None and (
                force_workspace
                or (suggestion.should_suggest and suggestion.confidence >= 0.8)
            ):
                logger.info(
                    "🚀 Auto-launching workspace from /api/chat (confidence=%.2f, force=%s)",
                    suggestion.confidence, force_workspace,
                )
                yield f"data: {json.dumps({'status': 'workspace_detected', 'confidence': round(suggestion.confidence, 2), 'task_type': suggestion.task_type, 'task_type_label': suggestion.task_type_label})}\n\n"
                from workspace.chat_bridge import stream_workspace_launch_as_chat
                pool = getattr(request.app.state, "pg_pool", None)
                async for line in stream_workspace_launch_as_chat(
                    message=current_message_content,
                    history=req.history or [],
                    user_id=current_user.id,
                    session_id=req.session_id,
                    pool=pool,
                    agent_id="local",
                    model_name="",
                    task_brief=suggestion.task_brief or current_message_content,
                    # force_workspace = user explicitly asked → "user" (unchanged);
                    # detector-driven escalation → "auto" (heavy tools withheld).
                    launch_mode=("user" if force_workspace else "auto"),
                ):
                    yield line
                return

            if suggestion is not None and suggestion.should_suggest and suggestion.confidence >= 0.4:
                logger.info(
                    "💡 Emitting workspace suggestion (confidence=%.2f, type=%s)",
                    suggestion.confidence, suggestion.task_type,
                )
                yield (
                    "data: "
                    + json.dumps({
                        "status": "workspace_suggestion",
                        "suggestion": suggestion.to_dict(),
                    })
                    + "\n\n"
                )
                # Fall through to the normal chat path — user still gets an answer.

            # ── 2. Auto-Research Detection (Perplexity-style) ──────────────────────────────
            if should_auto_research(req.message):
                logger.info(
                    "🔍 Auto-research triggered, redirecting to research pipeline"
                )
                yield f"data: {json.dumps({'status': 'researching', 'detail': 'Auto-research triggered, searching the web...'})}\n\n"
                try:
                    # Use streaming research agent for live progress updates
                    analysis = ""
                    sources = []
                    videos = []

                    async for event in async_research_agent_streaming(
                        current_message_content, req.model
                    ):
                        event_type = event.get("type")

                        if event_type == "search_query":
                            # Forward search query to frontend
                            query = event["query"]
                            yield f"data: {json.dumps({'status': 'researching', 'detail': f'Searching for: {query}', 'type': 'search_query', 'query': query})}\n\n"
                            logger.info(
                                f"[Auto-Research] Streaming search query: {query}"
                            )

                        elif event_type == "search_result":
                            # Forward search result to frontend
                            title = event["title"]
                            yield f"data: {json.dumps({'status': 'researching', 'detail': f'Found: {title}', 'type': 'search_result', 'title': title, 'url': event['url'], 'domain': event['domain']})}\n\n"

                        elif event_type == "reading":
                            # Forward reading progress to frontend
                            domain = event["domain"]
                            yield f"data: {json.dumps({'status': 'researching', 'detail': f'Reading {domain}...', 'type': 'reading', 'domain': domain, 'url': event['url']})}\n\n"

                        elif event_type == "analysis":
                            # Forward analysis progress
                            yield f"data: {json.dumps({'status': 'researching', 'detail': event.get('detail', 'Analyzing...')})}\n\n"

                        elif event_type == "complete":
                            # Store final result
                            result_data = event.get("result", {})
                            analysis = result_data.get("analysis", "")
                            sources = result_data.get("sources", [])
                            sources_found = result_data.get("sources_found", 0)
                            videos = result_data.get("videos", [])
                            logger.info(
                                f"[Auto-Research] Streaming research complete. Found {sources_found} sources"
                            )

                        elif event_type == "error":
                            analysis = (
                                f"Research Error: {event.get('error', 'Unknown error')}"
                            )

                    if analysis and not analysis.startswith("Research Error:"):
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

            # ── 6. NVIDIA NIM (Kimi K2.5) model branch ───────────────────────────────────────
            elif req.model == "nvidia-kimi":
                import time as _time

                _t0 = _time.monotonic()
                yield f"data: {json.dumps({'status': 'processing', 'detail': 'Querying NVIDIA NIM...'})}\n\n"

                pool = getattr(request.app.state, "pg_pool", None)
                if not pool:
                    yield f"data: {json.dumps({'status': 'error', 'error': 'Database not available'})}\n\n"
                    return

                nvidia_config = await get_user_api_key(pool, current_user.id, "nvidia")
                if not nvidia_config or not nvidia_config.get("api_key"):
                    yield f"data: {json.dumps({'status': 'error', 'error': 'NVIDIA API key not configured. Please add your key in Profile settings.'})}\n\n"
                    return

                nvidia_api_key = nvidia_config["api_key"]
                logger.info(f"⏱️ NVIDIA: key fetch took {_time.monotonic() - _t0:.2f}s")

                # Build messages (same system prompt logic as Moonshot branch)
                _t1 = _time.monotonic()
                system_prompt_path = os.path.join(
                    os.path.dirname(__file__), "system_prompt.txt"
                )
                try:
                    with open(system_prompt_path, "r", encoding="utf-8") as f:
                        system_prompt = f.read().strip()
                except FileNotFoundError:
                    system_prompt = 'You are "Jarves", a voice-first local assistant.'

                artifact_instructions_path = os.path.join(
                    os.path.dirname(__file__),
                    "prompts",
                    "artifact_instructions_code.txt",
                )
                try:
                    with open(artifact_instructions_path, "r", encoding="utf-8") as f:
                        system_prompt += f"\n\n{f.read().strip()}"
                except FileNotFoundError:
                    pass

                _t2 = _time.monotonic()
                local_rag_context = await get_local_rag_context(current_message_content)
                logger.info(
                    f"⏱️ NVIDIA: RAG lookup took {_time.monotonic() - _t2:.2f}s (prompt so far: {len(system_prompt)} chars)"
                )
                if local_rag_context:
                    system_prompt += f"\n\n--- RELEVANT DOCUMENTATION ---\n{local_rag_context}\n--- END ---"

                messages = [{"role": "system", "content": system_prompt}]
                for msg in history[:-1]:
                    messages.append({"role": msg["role"], "content": msg["content"]})
                messages.append({"role": "user", "content": current_message_content})

                total_prompt_chars = sum(len(m["content"]) for m in messages)
                logger.info(
                    f"🟢 Using NVIDIA NIM: moonshotai/kimi-k2.5 | thinking_mode={req.thinking_mode} | "
                    f"messages={len(messages)} total_prompt_chars={total_prompt_chars} | "
                    f"pre-request setup took {_time.monotonic() - _t0:.2f}s"
                )

                # NVIDIA NIM Kimi K2.5 with thinking returns TWO delta fields:
                #   delta.reasoning_content — chain-of-thought (thinking phase)
                #   delta.content           — final answer (response phase)
                # We collect both: thinking wrapped in <think> tags so the existing
                # reasoning extractor strips it out before TTS and history saving.
                response_text = ""
                _thinking_buf = ""
                _answer_buf = ""
                _chunk_count = 0
                _thinking_chunk_count = 0
                _answer_chunk_count = 0
                _ttft = None  # time-to-first-token
                _t_stream_start = _time.monotonic()
                try:
                    logger.info(
                        f"🔵 NVIDIA NIM: opening stream (thinking={req.thinking_mode})"
                    )
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(300.0, connect=10.0)
                    ) as client:
                        async with client.stream(
                            "POST",
                            "https://integrate.api.nvidia.com/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {nvidia_api_key}",
                                "Content-Type": "application/json",
                                "Accept": "text/event-stream",
                            },
                            json={
                                "model": "moonshotai/kimi-k2.5",
                                "messages": messages,
                                "temperature": 1.0,
                                "max_tokens": 16384,
                                "stream": True,
                                "chat_template_kwargs": {"thinking": req.thinking_mode},
                                "stream_options": {"include_usage": True},
                            },
                        ) as resp:
                            logger.info(
                                f"🔵 NVIDIA NIM: response status={resp.status_code} headers={dict(resp.headers)}"
                            )
                            if resp.status_code != 200:
                                err = await resp.aread()
                                err_text = err.decode()[:500]
                                logger.error(
                                    f"🔴 NVIDIA NIM: upstream error {resp.status_code}: {err_text}"
                                )
                                yield f"data: {json.dumps({'status': 'error', 'error': f'NVIDIA NIM error {resp.status_code}: {err_text}'})}\n\n"
                                return
                            logger.info(
                                "🔵 NVIDIA NIM: stream opened, reading chunks..."
                            )
                            async for line in resp.aiter_lines():
                                _chunk_count += 1
                                if line == "data: [DONE]":
                                    logger.info(
                                        f"🔵 NVIDIA NIM: received [DONE] after {_chunk_count} lines"
                                    )
                                    continue
                                if line.startswith("data: "):
                                    try:
                                        chunk = json.loads(line[6:])
                                        choices = chunk.get("choices", [])
                                        if not choices:
                                            # Could be a usage chunk
                                            usage = chunk.get("usage")
                                            if usage:
                                                logger.info(
                                                    f"🔵 NVIDIA NIM usage: {usage}"
                                                )
                                            continue
                                        delta = choices[0].get("delta", {})
                                        finish_reason = choices[0].get("finish_reason")
                                        if finish_reason:
                                            logger.info(
                                                f"🔵 NVIDIA NIM: finish_reason={finish_reason}"
                                            )

                                        thinking_chunk = (
                                            delta.get("reasoning_content") or ""
                                        )
                                        answer_chunk = delta.get("content") or ""

                                        if thinking_chunk:
                                            _thinking_chunk_count += 1
                                            _thinking_buf += thinking_chunk
                                            if req.thinking_mode:
                                                yield f"data: {json.dumps({'status': 'thinking', 'content': thinking_chunk})}\n\n"

                                        if answer_chunk:
                                            _answer_chunk_count += 1
                                            if _ttft is None:
                                                _ttft = (
                                                    _time.monotonic() - _t_stream_start
                                                )
                                                logger.info(
                                                    f"⏱️ NVIDIA NIM: time-to-first-token = {_ttft:.2f}s"
                                                )
                                            _answer_buf += answer_chunk
                                            yield f"data: {json.dumps({'status': 'streaming', 'content': answer_chunk})}\n\n"

                                        # Log delta keys to catch unexpected fields
                                        delta_keys = [k for k, v in delta.items() if v]
                                        if delta_keys and _chunk_count % 50 == 1:
                                            logger.debug(
                                                f"🔵 NVIDIA NIM delta keys at chunk {_chunk_count}: {delta_keys}"
                                            )

                                    except json.JSONDecodeError as je:
                                        logger.warning(
                                            f"🟡 NVIDIA NIM: JSON decode error on line: {line[:100]} — {je}"
                                        )
                                    except Exception as ce:
                                        logger.warning(
                                            f"🟡 NVIDIA NIM: chunk parse error: {ce}"
                                        )

                    _total_time = _time.monotonic() - _t_stream_start
                    logger.info(
                        f"🟢 NVIDIA NIM complete: total_time={_total_time:.2f}s TTFT={_ttft:.2f}s "
                        f"total_lines={_chunk_count} "
                        f"thinking_chunks={_thinking_chunk_count} ({len(_thinking_buf)} chars) "
                        f"answer_chunks={_answer_chunk_count} ({len(_answer_buf)} chars) "
                        f"tokens/s≈{len(_answer_buf) / max(_total_time, 0.1):.0f} chars/s"
                    )
                    if not _answer_buf and not _thinking_buf:
                        logger.error(
                            "🔴 NVIDIA NIM: both buffers empty — no content received from stream!"
                        )
                    elif not _answer_buf:
                        logger.warning(
                            f"🟡 NVIDIA NIM: answer_buf empty but thinking_buf has {len(_thinking_buf)} chars. "
                            f"thinking_mode={req.thinking_mode}. Model may have responded only via reasoning_content."
                        )

                    # Build response_text: thinking in <think> tags + final answer
                    if _thinking_buf:
                        response_text = (
                            f"<think>{_thinking_buf}</think>\n\n{_answer_buf}"
                        )
                    else:
                        response_text = _answer_buf
                except Exception as e:
                    logger.error(
                        f"🔴 NVIDIA NIM stream exception: {type(e).__name__}: {e}"
                    )
                    yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
                    return

            # ── 7. Moonshot/Kimi model branch ────────────────────────────────────────────────
            elif is_moonshot_model(req.model):
                yield f"data: {json.dumps({'status': 'processing', 'detail': 'Querying Moonshot AI...'})}\n\n"

                # Get user's Moonshot API key
                pool = getattr(request.app.state, "pg_pool", None)
                if not pool:
                    yield f"data: {json.dumps({'status': 'error', 'error': 'Database not available'})}\n\n"
                    return

                moonshot_config = await get_user_api_key(
                    pool, current_user.id, "moonshot"
                )

                if not moonshot_config or not moonshot_config.get("api_key"):
                    logger.error(
                        f"Moonshot API key not found or empty for user {current_user.id}"
                    )
                    yield f"data: {json.dumps({'status': 'error', 'error': 'Moonshot API key not configured. Please add your API key in Profile settings.'})}\n\n"
                    return

                # Debug: Log API key info (safely)
                api_key = moonshot_config["api_key"]
                if len(api_key) > 0:
                    prefix = api_key[:4] if len(api_key) >= 4 else api_key[:2]
                    suffix = api_key[-4:] if len(api_key) >= 4 else api_key[-2:]
                    middle_len = max(0, len(api_key) - len(prefix) - len(suffix))
                    middle = "*" * middle_len
                    masked_key = f"{prefix}{middle}{suffix}"
                    logger.info(
                        f"🌙 Moonshot API key: {masked_key} (length={len(api_key)})"
                    )
                else:
                    logger.error("🌙 Moonshot API key is EMPTY!")

                # Create Moonshot client with user's API key
                moonshot_client = MoonshotClient(
                    api_key=api_key,
                    base_url=moonshot_config.get("api_url") or MOONSHOT_BASE_URL,
                )

                # Get the correct model ID
                moonshot_model_id = get_moonshot_model_id(req.model)

                # Build messages
                system_prompt_path = os.path.join(
                    os.path.dirname(__file__), "system_prompt.txt"
                )
                try:
                    with open(system_prompt_path, "r", encoding="utf-8") as f:
                        system_prompt = f.read().strip()
                except FileNotFoundError:
                    system_prompt = (
                        'You are "Jarves", a voice-first local assistant. '
                        "Reply in ≤25 spoken-style words, sprinkling brief Spanish when natural."
                    )

                # Load artifact instructions (CODE-BASED approach)
                artifact_instructions_path = os.path.join(
                    os.path.dirname(__file__),
                    "prompts",
                    "artifact_instructions_code.txt",
                )
                try:
                    with open(artifact_instructions_path, "r", encoding="utf-8") as f:
                        artifact_instructions = f.read().strip()
                    system_prompt += f"\n\n{artifact_instructions}"
                    logger.info(
                        "📦 Added CODE-BASED artifact instructions to system prompt"
                    )
                except FileNotFoundError:
                    logger.warning("Artifact instructions file not found, skipping")
                except Exception as e:
                    logger.warning(f"Failed to load artifact instructions: {e}")

                # Check if it's a reasoning model
                is_reasoning_model = (
                    "k2.5" in req.model.lower() or "k2" in req.model.lower()
                )

                if is_reasoning_model:
                    system_prompt += (
                        "\n\nIMPORTANT: When reasoning through problems, wrap your thinking process in <think>...</think> tags. "
                        "This allows your reasoning to be shown separately from your final answer."
                    )

                # Add RAG context if available
                local_rag_context = await get_local_rag_context(current_message_content)
                if local_rag_context:
                    system_prompt += (
                        f"\n\n--- RELEVANT DOCUMENTATION FROM LOCAL CORPUS ---\n"
                        f"{local_rag_context}\n"
                        "--- END OF DOCUMENTATION CONTEXT ---"
                    )

                messages = [{"role": "system", "content": system_prompt}]
                for msg in history[:-1]:
                    messages.append({"role": msg["role"], "content": msg["content"]})
                messages.append({"role": "user", "content": current_message_content})

                logger.info(f"🌙 Using Moonshot AI with model: {moonshot_model_id}")

                # Stream response from Moonshot
                response_text = ""
                try:
                    async for chunk in moonshot_client.chat_completion_stream(
                        model=moonshot_model_id, messages=messages
                    ):
                        response_text += chunk
                        yield f"data: {json.dumps({'status': 'streaming', 'content': chunk})}\n\n"
                except Exception as e:
                    logger.error(f"Moonshot API error: {e}")
                    yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
                    return

            # ── 7. Ollama LLM generation branch (with heartbeats) ────────────────────────────
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

                # Load artifact instructions (CODE-BASED approach)
                artifact_instructions_path = os.path.join(
                    os.path.dirname(__file__),
                    "prompts",
                    "artifact_instructions_code.txt",
                )
                try:
                    with open(artifact_instructions_path, "r", encoding="utf-8") as f:
                        artifact_instructions = f.read().strip()
                    system_prompt += f"\n\n{artifact_instructions}"
                    logger.info(
                        "📦 Added CODE-BASED artifact instructions to system prompt"
                    )
                except FileNotFoundError:
                    logger.warning("Artifact instructions file not found, skipping")
                except Exception as e:
                    logger.warning(f"Failed to load artifact instructions: {e}")

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
                    logger.debug(
                        f"[Low VRAM Mode] Skipping model unload for {req.model} — vLLM/llama-server manage memory automatically"
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

            # ── 7.5 Artifact Detection ──────────────────────────────────────────────────────
            artifact_info = None
            try:
                logger.info("🔍 Starting artifact detection...")

                # First, try CODE-BASED document generation (new approach)
                pool = getattr(request.app.state, "pg_pool", None)
                if not pool:
                    logger.warning(
                        "⚠️ Database pool not available for artifact creation"
                    )

                # Check for document generation code (Excel, Word, PDF, PowerPoint)
                document_types = ["spreadsheet", "document", "pdf", "presentation"]
                code_artifact_type = None
                code_title = None

                logger.info(
                    f"🔍 Checking for document code in response (length: {len(final_answer)} chars)"
                )

                logger.info(
                    f"🔍 Checking for document generation code in response ({len(final_answer)} chars)"
                )
                logger.info(f"🔍 Looking for code blocks: {document_types}")

                for doc_type in document_types:
                    logger.info(f"🔍 Checking for {doc_type} code...")
                    doc_code = extract_document_code(final_answer, doc_type)
                    if doc_code:
                        code_artifact_type = doc_type
                        code_title = f"Generated {doc_type.capitalize()}"
                        logger.info(
                            f"✅ Found {doc_type} generation code ({len(doc_code)} chars)"
                        )
                        # Log first 200 chars of code for debugging
                        logger.info(f"📝 Code preview: {doc_code[:200]}...")
                        break
                    else:
                        logger.info(f"❌ No {doc_type} code found")

                # Fallback: Auto-detect document type from imports
                if not code_artifact_type:
                    logger.info("🔍 Trying auto-detection from imports...")
                    auto_result = auto_detect_document_type(final_answer)
                    if auto_result:
                        code_artifact_type, doc_code = auto_result
                        code_title = f"Generated {code_artifact_type.capitalize()}"
                        logger.info(
                            f"✅ Auto-detected {code_artifact_type} from imports"
                        )

                if code_artifact_type:
                    # ASYNC JOB-BASED GENERATION
                    logger.info(
                        f"📦 Async job-based {code_artifact_type} generation detected"
                    )
                    yield f"data: {json.dumps({'status': 'processing', 'detail': f'Queuing {code_artifact_type} generation...'})}\n\n"

                    try:
                        # Create async job for document generation
                        import asyncpg
                        from job_queue import get_job_queue

                        # Generate IDs
                        job_id = str(uuid.uuid4())
                        artifact_id = str(uuid.uuid4())

                        if pool:
                            # Insert job into document_jobs table
                            # Note: message_id is not available in streaming context, using NULL
                            await pool.execute(
                                """
                                INSERT INTO document_jobs (
                                    id, user_id, session_id, message_id, job_type,
                                    status, payload, priority, created_at
                                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                                """,
                                job_id,
                                current_user.id,
                                session_id if session_id else None,
                                None,  # message_id not available in streaming context
                                code_artifact_type,
                                "pending",
                                json.dumps(
                                    {
                                        "code": doc_code,
                                        "title": code_title,
                                        "artifact_id": artifact_id,
                                    }
                                ),
                                0,
                            )
                            logger.info(f"💾 Created document job {job_id} in database")

                            # Enqueue job in job queue
                            queue = await get_job_queue()
                            await queue.send(
                                name="generate-document",
                                data={
                                    "document_job_id": job_id,
                                    "code": doc_code,
                                    "document_type": code_artifact_type,
                                    "title": code_title,
                                    "user_id": current_user.id,
                                    "session_id": str(session_id)
                                    if session_id
                                    else None,
                                    "artifact_id": artifact_id,
                                },
                                retry_limit=3,
                                priority=0,
                            )
                            logger.info(f"📨 Enqueued job {job_id} for processing")

                            # Build artifact_info with job reference (frontend will poll via SSE)
                            artifact_info = {
                                "id": artifact_id,
                                "type": code_artifact_type,
                                "title": code_title,
                                "status": "generating",
                                "download_url": f"/api/artifacts/{artifact_id}/download",
                                "job_id": job_id,
                                "code": doc_code,  # Include the code so users can view it later
                            }
                            logger.info(
                                f"📦 Created async job: {job_id} for artifact {artifact_id}"
                            )

                            # Notify frontend that job is queued
                            detail_msg = (
                                f"{code_artifact_type.capitalize()} generation queued"
                            )
                            yield f"data: {json.dumps({'status': 'processing', 'detail': detail_msg, 'job_id': job_id, 'artifact_id': artifact_id})}\n\n"

                            # Clean response by removing the code block
                            final_answer = clean_response_content(final_answer)
                            logger.info(f"🧹 Cleaned response, removed code block")
                        else:
                            logger.error("❌ No database pool available to create job")

                    except Exception as job_error:
                        logger.exception(
                            f"💥 Exception creating async job: {job_error}"
                        )
                        # Fallback: try synchronous generation
                        logger.warning("⚠️ Falling back to synchronous generation")
                        try:
                            # Use single artifact_id for both generation AND database record
                            sync_artifact_id = str(uuid.uuid4())
                            doc_result = generate_document_from_code(
                                llm_response=final_answer,
                                artifact_type=code_artifact_type,
                                title=code_title,
                                artifact_id=sync_artifact_id,
                                use_docker=True,
                            )
                            if doc_result.get("success") and pool:
                                # Get mime type based on artifact type
                                mime_types = {
                                    "spreadsheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    "document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    "pdf": "application/pdf",
                                    "presentation": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                                }
                                mime_type = mime_types.get(
                                    code_artifact_type, "application/octet-stream"
                                )

                                # Save artifact record to database
                                await pool.execute(
                                    """
                                    INSERT INTO artifacts (
                                        id, user_id, artifact_type, title,
                                        file_path, file_size, mime_type, status, created_at
                                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'ready', NOW())
                                    ON CONFLICT (id) DO UPDATE SET
                                        status = 'ready',
                                        file_path = EXCLUDED.file_path,
                                        file_size = EXCLUDED.file_size
                                    """,
                                    sync_artifact_id,
                                    current_user.id,
                                    code_artifact_type,
                                    code_title,
                                    doc_result.get("file_path"),
                                    doc_result.get("file_size", 0),
                                    mime_type,
                                )
                                logger.info(
                                    f"💾 Saved artifact {sync_artifact_id} to database"
                                )

                                artifact_info = {
                                    "id": sync_artifact_id,
                                    "type": code_artifact_type,
                                    "title": code_title,
                                    "status": "ready",
                                    "download_url": f"/api/artifacts/{sync_artifact_id}/download",
                                    "code": doc_code,
                                }
                                final_answer = clean_response_content(final_answer)
                            elif doc_result.get("success"):
                                logger.error(
                                    "❌ Document generated but no database pool to save record"
                                )
                            else:
                                logger.error(
                                    f"❌ Document generation failed: {doc_result.get('error')}"
                                )
                        except Exception as fallback_error:
                            logger.error(
                                f"❌ Fallback generation also failed: {fallback_error}"
                            )
                else:
                    logger.info("🔍 No document generation code found in response")

                # Fallback: Try JSON manifest approach (for websites/apps and backward compatibility)
                if not artifact_info:
                    logger.info("🔍 Attempting artifact detection from response...")
                    logger.debug(
                        f"Response preview (first 500 chars): {final_answer[:500] if final_answer else 'empty'}"
                    )

                    artifact_manifest = extract_artifact_manifest(final_answer)
                    if artifact_manifest:
                        logger.info(
                            f"✅ JSON manifest found: {artifact_manifest.get('artifact_type')}"
                        )

                    # If no manifest found, try to auto-detect Next.js/React project from code blocks
                    if not artifact_manifest:
                        logger.info(
                            "🔍 No JSON manifest, trying auto-detection from code blocks..."
                        )
                        artifact_manifest = extract_nextjs_project_from_codeblocks(
                            final_answer
                        )
                        if artifact_manifest:
                            logger.info(
                                f"✅ Auto-detected Next.js/React project: {len(artifact_manifest.get('content', {}).get('files', {}))} files"
                            )
                        else:
                            logger.info(
                                "❌ No project structure detected in code blocks"
                            )

                    if artifact_manifest:
                        logger.info(
                            f"📦 Artifact detected: {artifact_manifest.get('artifact_type')} - {artifact_manifest.get('title')}"
                        )
                        yield f"data: {json.dumps({'status': 'processing', 'detail': 'Creating artifact...'})}\n\n"

                        # Clean the final answer by removing the manifest
                        final_answer = clean_response_content(final_answer)

                        # Create artifact in database
                        if pool:
                            try:
                                manifest = ArtifactManifest(**artifact_manifest)
                                artifact_id = await artifact_storage.create_artifact(
                                    pool=pool,
                                    user_id=current_user.id,
                                    manifest=manifest,
                                    session_id=session_id if session_id else None,
                                )

                                # For document types, generate in background
                                artifact_type = manifest.artifact_type
                                if hasattr(artifact_type, "value"):
                                    artifact_type = artifact_type.value

                                if artifact_type not in ["website", "app", "code"]:
                                    # Generate document artifact in background
                                    import asyncio

                                    asyncio.create_task(
                                        artifact_storage.generate_artifact(
                                            pool, artifact_id
                                        )
                                    )
                                    artifact_status = "generating"
                                else:
                                    artifact_status = "ready"

                                artifact_info = {
                                    "id": str(artifact_id),
                                    "type": artifact_type,
                                    "title": manifest.title,
                                    "status": artifact_status,
                                }

                                # Add download URL for ready artifacts
                                if artifact_status == "ready" and artifact_type in [
                                    "website",
                                    "app",
                                    "code",
                                ]:
                                    artifact_info["preview_url"] = (
                                        f"/api/artifacts/{artifact_id}/preview"
                                    )
                                elif artifact_status == "generating":
                                    artifact_info["download_url"] = (
                                        f"/api/artifacts/{artifact_id}/download"
                                    )

                                logger.info(
                                    f"📦 Created artifact {artifact_id} ({artifact_status})"
                                )
                                logger.info(
                                    f"📦 Artifact info: {json.dumps(artifact_info)}"
                                )
                            except Exception as e:
                                logger.error(f"Failed to create artifact: {e}")
                                import traceback

                                logger.error(f"Traceback: {traceback.format_exc()}")
            except Exception as e:
                logger.warning(f"Artifact detection failed: {e}")

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
                        tts_engine=req.tts_engine,
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

            # Add artifact info to metadata so it persists with the message
            if artifact_info:
                msg_metadata["artifact"] = artifact_info
                logger.info(
                    f"💾 Added artifact to message metadata: {artifact_info['id']}"
                )
                logger.info(
                    f"📝 Artifact has code: {bool(artifact_info.get('code'))}, code length: {len(artifact_info.get('code', ''))}"
                )

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

            if artifact_info:
                response_data["artifact"] = artifact_info
                logger.info(
                    f"📦 Returning artifact in response: {artifact_info['type']} - {artifact_info['title']} ({artifact_info['status']})"
                )
                logger.info(f"📦 Artifact data: {json.dumps(artifact_info)}")

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

            # NEW: Process document files (PDF, DOCX) and convert to images
            if req.files:
                yield f"data: {json.dumps({'status': 'processing', 'detail': f'Converting {len(req.files)} document(s) to images...'})}\n\n"

                for file_idx, file_info in enumerate(req.files):
                    try:
                        file_name = file_info.get("name", f"file_{file_idx}")
                        file_data = file_info.get("data", "")
                        file_type = file_info.get("mimeType", "") or file_name

                        if not file_data:
                            logger.warning(f"📄 File {file_name}: No data provided")
                            continue

                        if not is_vision_compatible_file(file_type):
                            logger.warning(
                                f"📄 File {file_name}: Type {file_type} not compatible with vision"
                            )
                            continue

                        logger.info(
                            f"📄 Converting {file_name} ({file_type}) to images..."
                        )
                        yield f"data: {json.dumps({'status': 'processing', 'detail': f'Converting {file_name}...'})}\n\n"

                        # Convert file to images
                        file_images = convert_file_to_images(file_data, file_type)

                        if file_images:
                            logger.info(
                                f"📄 {file_name}: Converted to {len(file_images)} images"
                            )
                            for img_base64, mime_type in file_images:
                                processed_images.append(img_base64)
                        else:
                            logger.warning(
                                f"📄 {file_name}: No images generated from conversion"
                            )

                    except Exception as file_err:
                        logger.error(f"📄 Error converting file {file_idx}: {file_err}")
                        continue

            if not processed_images:
                yield f"data: {json.dumps({'status': 'error', 'error': 'No valid images provided. Please upload images or supported documents (PDF, DOCX).'})}\n\n"
                return

            # Build messages array
            messages = []
            system_prompt = (
                'You are "Harvis", an AI assistant with vision capabilities. '
                "Analyze the provided image(s) and respond helpfully to the user's question. "
                "Be concise but thorough in your visual analysis."
            )
            messages.append({"role": "system", "content": system_prompt})

            for msg in req.history:
                messages.append({"role": msg["role"], "content": msg["content"]})

            # Check if this is an NVIDIA NIM vision model (Kimi K2.5)
            if req.model == "nvidia-kimi":
                pool = getattr(request.app.state, "pg_pool", None)
                if not pool:
                    yield f"data: {json.dumps({'status': 'error', 'error': 'Database not available'})}\n\n"
                    return

                nvidia_config = await get_user_api_key(pool, current_user.id, "nvidia")
                if not nvidia_config or not nvidia_config.get("api_key"):
                    yield f"data: {json.dumps({'status': 'error', 'error': 'NVIDIA API key not configured. Add it in Profile settings.'})}\n\n"
                    return

                nvidia_api_key = nvidia_config["api_key"]

                # Build multimodal content — text + images (OpenAI image_url format)
                content = [{"type": "text", "text": req.message}]
                for img_b64 in processed_images:
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                        }
                    )
                messages.append({"role": "user", "content": content})

                logger.info(
                    f"🖼️ VISION: Using NVIDIA NIM Kimi K2.5 with {len(processed_images)} image(s)"
                )
                yield f"data: {json.dumps({'status': 'inference', 'detail': f'Analyzing with NVIDIA Kimi K2.5...'})}\n\n"

                try:
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(300.0, connect=10.0)
                    ) as client:
                        resp = await client.post(
                            "https://integrate.api.nvidia.com/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {nvidia_api_key}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "model": "moonshotai/kimi-k2.5",
                                "messages": messages,
                                "temperature": 1.0,
                                "max_tokens": 4096,
                            },
                        )
                    if resp.status_code != 200:
                        err = resp.text[:300]
                        logger.error(f"🖼️ VISION NVIDIA error {resp.status_code}: {err}")
                        yield f"data: {json.dumps({'status': 'error', 'error': f'NVIDIA vision error {resp.status_code}: {err}'})}\n\n"
                        return
                    data = resp.json()
                    response_text = data["choices"][0]["message"]["content"]
                    logger.info(f"🖼️ VISION NVIDIA: got {len(response_text)} chars")
                except Exception as e:
                    logger.error(f"🖼️ VISION NVIDIA exception: {e}")
                    yield f"data: {json.dumps({'status': 'error', 'error': f'NVIDIA vision error: {str(e)}'})}\n\n"
                    return

            # Check if this is a Moonshot vision model
            elif is_moonshot_model(req.model):
                # Use Moonshot API for vision
                pool = getattr(request.app.state, "pg_pool", None)
                if not pool:
                    yield f"data: {json.dumps({'status': 'error', 'error': 'Database not available'})}\n\n"
                    return

                moonshot_config = await get_user_api_key(
                    pool, current_user.id, "moonshot"
                )
                if not moonshot_config or not moonshot_config.get("api_key"):
                    yield f"data: {json.dumps({'status': 'error', 'error': 'Moonshot API key not configured'})}\n\n"
                    return

                try:
                    moonshot_client = MoonshotClient(
                        api_key=moonshot_config["api_key"],
                        base_url=moonshot_config.get("api_url") or MOONSHOT_BASE_URL,
                    )

                    # Format messages for Moonshot vision (OpenAI-compatible format)
                    content = [{"type": "text", "text": req.message}]
                    for img_b64 in processed_images:
                        content.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{img_b64}"
                                },
                            }
                        )

                    messages.append({"role": "user", "content": content})

                    moonshot_model_id = get_moonshot_model_id(req.model)
                    logger.info(
                        f"🖼️ VISION: Using Moonshot AI with model {moonshot_model_id} and {len(processed_images)} image(s)"
                    )

                    yield f"data: {json.dumps({'status': 'inference', 'detail': f'Analyzing with {moonshot_model_id}...'})}\n\n"

                    response_text = await moonshot_client.chat_completion(
                        model=moonshot_model_id, messages=messages
                    )

                    logger.info(
                        f"🖼️ VISION: Got Moonshot response ({len(response_text)} chars)"
                    )

                except Exception as e:
                    logger.error(f"🖼️ VISION: Moonshot request failed: {e}")
                    yield f"data: {json.dumps({'status': 'error', 'error': f'Moonshot vision error: {str(e)}'})}\n\n"
                    return
            else:
                # Use Ollama for vision
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

                response_data = ollama_response.json()
                logger.debug(f"🖼️ VISION: Raw Ollama response: {response_data}")

                # Try multiple response formats (different models may return content differently)
                response_text = (
                    response_data.get("message", {}).get("content", "").strip()
                )

                # If empty, try alternative formats
                if not response_text:
                    response_text = response_data.get("response", "").strip()
                if not response_text:
                    response_text = response_data.get("content", "").strip()
                if not response_text:
                    response_text = response_data.get("text", "").strip()
                if not response_text:
                    # Check if there's a choices array (OpenAI-style format)
                    choices = response_data.get("choices", [])
                    if choices and len(choices) > 0:
                        response_text = (
                            choices[0].get("message", {}).get("content", "").strip()
                        )
                        if not response_text:
                            response_text = choices[0].get("text", "").strip()

            # Debug: Log the actual structure if content is empty
            if not response_text:
                logger.error(
                    f"🖼️ VISION: Empty content! Response structure: {json.dumps(response_data, indent=2)[:1000]}"
                )
                # Also log if there's a done_reason or error
                if "done_reason" in response_data:
                    logger.error(
                        f"🖼️ VISION: done_reason = {response_data.get('done_reason')}"
                    )
                if "error" in response_data:
                    logger.error(f"🖼️ VISION: error = {response_data.get('error')}")

            logger.info(f"🖼️ VISION: Got response ({len(response_text)} chars)")

            # Check if response is empty and return error instead of saving empty content
            if not response_text:
                error_msg = "The vision model returned an empty response. This may be due to: (1) The model failed to process the image, (2) The image format is not supported, or (3) The model is not properly loaded. Please try again or check the model logs."
                logger.error(f"🖼️ VISION: {error_msg}")
                yield f"data: {json.dumps({'status': 'error', 'error': error_msg})}\n\n"
                return

            if req.low_vram:
                logger.debug(
                    f"[Low VRAM Mode] Skipping vision model unload for {req.model} — vLLM/llama-server manage memory automatically"
                )

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
                        # Use tts_engine from request if available, default to qwen
                        tts_engine = getattr(req, "tts_engine", "qwen")
                        async for event in run_tts_with_heartbeats(
                            text=final_answer,
                            audio_prompt=HARVIS_VOICE_PATH,
                            exaggeration=0.5,
                            temperature=0.5,
                            cfg_weight=2.0,
                            auto_unload=req.low_vram,
                            tts_engine=tts_engine,
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


# ════════════════════════════════════════════════════════════════════════════
# OWUI-compat AUDIO (S4) — STT/TTS over the OpenWebUI /api/v1/audio/* contract.
# Thin wrappers over Harvis's existing Whisper (transcribe_with_whisper_optimized)
# and TTS (safe_generate_speech_optimized). Living in main.py keeps them in scope
# of those helpers + get_current_user without a circular import on owui_compat.
# /api/config already reports audio.{tts,stt}.engine="" so OWUI routes here.
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/audio/config", tags=["audio"])
async def owui_audio_config(current_user: UserResponse = Depends(get_current_user)):
    """OWUI reads this to decide STT/TTS routing. Server-side engines (empty
    OPENAI_API_BASE_URL = same-origin) so the UI calls our endpoints, not the
    browser Web Speech API."""
    tts_status = synthesis.status()
    stt_status = transcription_status()
    return {
        "tts": {
            "OPENAI_API_BASE_URL": "",
            "OPENAI_API_KEY": "",
            "API_KEY": "",
            "ENGINE": "",
            "MODEL": tts_status.get("model") or tts_status.get("engine") or "",
            "VOICE": tts_status.get("voice", synthesis.DEFAULT_VOICE),
            "SPLIT_ON": "punctuation",
        },
        "stt": {
            "OPENAI_API_BASE_URL": "",
            "OPENAI_API_KEY": "",
            "ENGINE": "",
            "MODEL": stt_status.get("model") or "whisper-1",
            "WHISPER_MODEL": os.getenv("WHISPER_MODEL", "base"),
            "SUPPORTED_CONTENT_TYPES": ["audio/*"],
        },
        # Harvis-specific: which side of the wire does the work. The client reads
        # these to keep browser Kokoro as the playback path when the server isn't
        # synthesizing, instead of calling an endpoint that will 503.
        "harvis": {"tts": tts_status, "stt": stt_status},
    }


@app.post("/api/v1/audio/config/update", tags=["audio"])
async def owui_audio_config_update(
    request: Request, current_user: UserResponse = Depends(require_admin)
):
    """Accept admin audio-config edits. v1: echo back (engines are fixed to the
    Harvis Whisper/TTS stack); persisting per-field config is a later pass.

    Admin-gated server-side. This is server-wide configuration and was previously
    reachable by ANY signed-in user — harmless only because the handler is a
    no-op echo. Gating it now means the day it starts persisting, it is already
    safe rather than needing to be remembered."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    return body or (await owui_audio_config(current_user))


@app.post("/api/v1/audio/transcriptions", tags=["audio"])
async def owui_audio_transcriptions(
    file: UploadFile = File(...),
    language: str = Form(None),
    current_user: UserResponse = Depends(get_current_user),
):
    """OWUI STT: multipart audio → Harvis Whisper → {text}. Mirrors /api/mic-chat's
    save-then-transcribe, minus the LLM/TTS legs (OWUI just wants the transcript).

    `language` is the caller's own preference (Settings → Audio) and overrides the
    server default. It used to be accepted and silently dropped, which made the
    setting look effective while every request still auto-detected."""
    contents = await file.read()
    _, ext = os.path.splitext(file.filename or "")
    if not ext:
        ext = ".wav"
    tmp_path = os.path.join(tempfile.gettempdir(), f"owui_stt_{uuid.uuid4()}{ext}")
    try:
        with open(tmp_path, "wb") as f:
            f.write(contents)
        logger.info("🎤 OWUI STT: %s (%d bytes) → %s", file.filename, len(contents), tmp_path)
        result = await run_in_threadpool(
            transcribe_audio, tmp_path, True, (language or "").strip() or None
        )
        text = (result or {}).get("text", "") if isinstance(result, dict) else str(result or "")
        return {"text": text.strip()}
    except TranscriptionUnavailable as e:
        # The server was never going to transcribe this — a provider setting, not
        # a fault. 503 with the message, so the client can say something useful.
        logger.warning("🎤 OWUI STT unavailable: %s", e)
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error("❌ OWUI STT failed: %s", e)
        raise HTTPException(500, f"Transcription failed: {e}")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@app.post("/api/v1/audio/speech", tags=["audio"])
async def owui_audio_speech(
    request: Request, current_user: UserResponse = Depends(get_current_user)
):
    """OWUI TTS: {input, voice, model?, speed?} → audio bytes (the OpenAI
    /audio/speech contract — raw audio in the response body).

    Which engine actually speaks is `synthesis.py`'s call: in-process Piper/Qwen
    on a voice-pack build, the ONNX voice sidecar when HARVIS_TTS_PROVIDER=
    sidecar, or an honest refusal when the browser owns playback."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    text = (body.get("input") or "").strip()
    if not text:
        raise HTTPException(400, "Missing 'input' text")

    speed = body.get("speed")
    try:
        speed = float(speed) if speed is not None else None
    except (TypeError, ValueError):
        speed = None

    try:
        audio_bytes, mime = await run_in_threadpool(
            tts_synthesize,
            text,
            body.get("voice"),
            speed,
            body.get("response_format"),
            body.get("model"),
        )
    except SynthesisUnavailable as e:
        # The server was never going to speak this — a provider setting, not a
        # fault. 503 with the message so the client can fall back to its own
        # Kokoro rather than showing an error.
        logger.warning("🔊 TTS unavailable: %s", e)
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error("❌ TTS failed: %s", e)
        raise HTTPException(500, f"Speech synthesis failed: {e}")
    return Response(content=audio_bytes, media_type=mime)


@app.get("/api/v1/audio/models", tags=["audio"])
async def owui_audio_models(current_user: UserResponse = Depends(get_current_user)):
    """TTS engines this server can actually reach, not a fixed list."""
    info = synthesis.status()
    if info["provider"] == synthesis.SIDECAR:
        model = info.get("model") or "voice-onnx"
        return {"models": [{"id": model, "name": "ONNX voice service"}]}
    if info["provider"] == synthesis.LOCAL:
        models = [{"id": "piper", "name": "Piper (CPU)"}]
        fallback = info.get("fallback")
        if fallback and fallback != "piper":
            models.append({"id": fallback, "name": f"{fallback.title()} TTS"})
        return {"models": models}
    return {"models": []}


@app.get("/api/v1/audio/voices", tags=["audio"])
async def owui_audio_voices(current_user: UserResponse = Depends(get_current_user)):
    """Voices the configured provider offers. A voice list the server can't
    honour is worse than an empty one — the picker would offer names that
    silently fall back to something else."""
    try:
        return {"voices": await run_in_threadpool(synthesis.voices)}
    except SynthesisUnavailable as e:
        logger.warning("🔊 voice list unavailable: %s", e)
        return {"voices": [], "detail": str(e)}


# ════════════════════════════════════════════════════════════════════════════
# OWUI-compat FILES (S3) — attachment upload/serve over /api/v1/files/*.
# Stores bytes on disk + a row in owui_files; the facade chat path resolves these
# into the model prompt (text → context block, image → vision part). No RAG in v1.
# ════════════════════════════════════════════════════════════════════════════

def _owui_file_obj(row: dict) -> dict:
    """Shape a owui_files row the way OWUI's frontend expects a file object."""
    meta = row.get("meta") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    created = row.get("created_at")
    ts = int(created.timestamp()) if hasattr(created, "timestamp") else int(time.time())
    return {
        "id": row["id"],
        "user_id": str(row["user_id"]),
        "hash": row["id"],
        "filename": row["filename"],
        "data": {},
        "meta": {
            "name": row["filename"],
            "content_type": row.get("content_type") or "application/octet-stream",
            "size": row.get("size") or 0,
            **meta,
        },
        "created_at": ts,
        "updated_at": ts,
    }


@app.post("/api/v1/files/", tags=["files"])
async def owui_files_upload(
    request: Request,
    file: UploadFile = File(...),
    metadata: str = Form(None),
    current_user: UserResponse = Depends(get_current_user),
):
    """Store an uploaded attachment + return its OWUI file object."""
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(503, "Storage unavailable")
    os.makedirs(OWUI_FILES_DIR, exist_ok=True)
    file_id = str(uuid.uuid4())
    _, ext = os.path.splitext(file.filename or "")
    disk_path = os.path.join(OWUI_FILES_DIR, f"{file_id}{ext}")
    contents = await file.read()
    with open(disk_path, "wb") as f:
        f.write(contents)
    meta = {}
    if metadata:
        try:
            meta = json.loads(metadata)
        except Exception:
            meta = {}
    content_type = file.content_type or "application/octet-stream"
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO owui_files (id, user_id, filename, path, content_type, size, meta) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7)",
            file_id, int(current_user.id), file.filename or file_id, disk_path,
            content_type, len(contents), json.dumps(meta),
        )
    logger.info("📎 OWUI file upload: %s (%s, %d bytes) id=%s",
                file.filename, content_type, len(contents), file_id)
    return _owui_file_obj({
        "id": file_id, "user_id": int(current_user.id), "filename": file.filename or file_id,
        "content_type": content_type, "size": len(contents), "meta": meta, "created_at": None,
    })


@app.get("/api/v1/files/{file_id}/process/status", tags=["files"])
async def owui_files_process_status(
    file_id: str, current_user: UserResponse = Depends(get_current_user)
):
    """OWUI polls this after upload (NDJSON stream). We inject raw content at chat
    time (no RAG), so report completed immediately."""
    async def _gen():
        yield json.dumps({"id": file_id, "status": "completed", "progress": 100}) + "\n"
    return StreamingResponse(_gen(), media_type="application/x-ndjson")


async def _owui_file_row(pool, file_id: str, user_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM owui_files WHERE id=$1 AND user_id=$2", file_id, int(user_id)
        )


@app.get("/api/v1/files/{file_id}", tags=["files"])
async def owui_files_get(
    file_id: str, request: Request, current_user: UserResponse = Depends(get_current_user)
):
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(503, "Storage unavailable")
    row = await _owui_file_row(pool, file_id, current_user.id)
    if not row:
        raise HTTPException(404, "File not found")
    return _owui_file_obj(dict(row))


@app.get("/api/v1/files/{file_id}/content", tags=["files"])
async def owui_files_content(
    file_id: str, request: Request, current_user: UserResponse = Depends(get_current_user)
):
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(503, "Storage unavailable")
    row = await _owui_file_row(pool, file_id, current_user.id)
    if not row or not os.path.exists(row["path"]):
        raise HTTPException(404, "File not found")
    return FileResponse(
        row["path"],
        media_type=row["content_type"] or "application/octet-stream",
        filename=row["filename"],
    )


@app.delete("/api/v1/files/{file_id}", tags=["files"])
async def owui_files_delete(
    file_id: str, request: Request, current_user: UserResponse = Depends(get_current_user)
):
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(503, "Storage unavailable")
    row = await _owui_file_row(pool, file_id, current_user.id)
    if row:
        try:
            os.remove(row["path"])
        except OSError:
            pass
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM owui_files WHERE id=$1 AND user_id=$2",
                               file_id, int(current_user.id))
    return {"id": file_id, "deleted": True}


@app.post("/api/uploads", tags=["uploads"])
async def upload_file(
    file: UploadFile = File(...),
    current_user: UserResponse = Depends(get_current_user),
):
    """
    Store an uploaded file (image, PDF, DOCX) and return a file_id that can
    be passed to OpenClaw via a workspace task brief.

    The file_id is then used with POST /api/tools/file-analyze so OpenClaw
    can have Kimi vision analyze the document and recreate it as a DOCX.
    """
    ALLOWED_MIME_PREFIXES = (
        "image/",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml",
        "application/msword",
        "application/rtf",
        # Text & data formats — explicit MIME prefixes (the extension allowlist
        # below is the real workhorse for non-standard text MIME types).
        "text/",
        "application/json",
        "application/xml",
        "application/yaml",
        "application/toml",
        "application/sql",
        "application/graphql",
        "application/x-ndjson",
        "application/x-jsonlines",
        "application/x-ipynb",
        "application/x-protobuf",
    )

    # Extension allowlist for files browsers send as application/octet-stream
    # (most non-standard text formats hit this path). Keep this list in sync
    # with SUPPORTED_FILE_TYPES in front_end/.../chat-input.tsx.
    ALLOWED_EXTENSIONS = {
        # Documents
        ".pdf", ".docx", ".doc", ".rtf",
        # Text & docs
        ".txt", ".md", ".mdx", ".rst", ".adoc", ".org", ".tex",
        # Data
        ".csv", ".tsv", ".json", ".ndjson", ".jsonl", ".xml",
        ".yaml", ".yml", ".toml", ".sql", ".graphql", ".gql", ".proto",
        # Logs & diffs
        ".log", ".diff", ".patch",
        # Config
        ".ini", ".conf", ".cfg", ".properties", ".env",
        # Web
        ".html", ".htm", ".css", ".scss", ".sass", ".less",
        ".vue", ".svelte", ".js", ".jsx", ".ts", ".tsx",
        # Programming
        ".py", ".go", ".rs", ".rb", ".php", ".java", ".kt", ".swift",
        ".scala", ".dart", ".lua", ".pl", ".r", ".cs",
        ".c", ".h", ".cpp", ".hpp", ".cc", ".m", ".mm",
        # Shell
        ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat",
        # Notebooks & images (images also matched via MIME above)
        ".ipynb",
        ".png", ".jpg", ".jpeg", ".gif", ".webp",
    }

    mime_type = file.content_type or "application/octet-stream"
    filename_lower = (file.filename or "").lower()
    file_ext = os.path.splitext(filename_lower)[1]
    mime_ok = any(mime_type.startswith(p) for p in ALLOWED_MIME_PREFIXES)
    ext_ok = file_ext in ALLOWED_EXTENSIONS
    if not (mime_ok or ext_ok):
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type: {mime_type} ({file_ext or 'no extension'}). "
                f"Allowed: images, PDF, DOCX, common text/code/config files."
            ),
        )

    # Derive safe extension. Prefer the actual filename extension when it's
    # one we recognize; fall back to MIME-based guess for legacy uploads.
    _EXT_MAP = {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/msword": ".doc",
        "application/rtf": ".rtf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }
    if file_ext in ALLOWED_EXTENSIONS:
        ext = file_ext
    else:
        ext = _EXT_MAP.get(mime_type, "")
        if not ext and mime_type.startswith("image/"):
            ext = f".{mime_type.split('/')[1]}"
        elif not ext and mime_type.startswith("text/"):
            ext = ".txt"

    file_id = str(uuid.uuid4())
    stored_path = os.path.join(IMAGES_DIR, f"{file_id}{ext}")
    meta_path = os.path.join(IMAGES_DIR, f"{file_id}.meta.json")

    try:
        contents = await file.read()
        with open(stored_path, "wb") as f_out:
            f_out.write(contents)
        import json as _json

        with open(meta_path, "w") as f_meta:
            _json.dump(
                {
                    "file_id": file_id,
                    "filename": file.filename or f"upload{ext}",
                    "mime_type": mime_type,
                    "stored_path": stored_path,
                    "user_id": current_user.id,
                    "size": len(contents),
                },
                f_meta,
            )
    except Exception as exc:
        logger.error("upload_file: failed to store file: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to store file: {exc}")

    logger.info(
        "upload_file: file_id=%s filename=%r mime=%s size=%d user=%d",
        file_id,
        file.filename,
        mime_type,
        len(contents),
        current_user.id,
    )

    return {
        "file_id": file_id,
        "filename": file.filename,
        "mime_type": mime_type,
        "size": len(contents),
    }


@app.post("/api/analyze-screen", tags=["vision"])
async def analyze_screen(req: ScreenAnalysisRequest):
    try:
        # Free VRAM for the vision model Ollama is about to load
        logger.info("🖼️ Starting screen analysis - clearing ALL GPU memory")
        unload_all_models()  # Unload everything for maximum memory

        # Decode base64 image and save to a temporary file
        image_data = base64.b64decode(req.image.split(",")[1])
        temp_image_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.png")
        with open(temp_image_path, "wb") as f:
            f.write(image_data)

        # Caption the image with whatever vision model the user has installed
        vision_prompt = "Describe this image in detail."
        vision_caption = query_vision(temp_image_path, vision_prompt)
        os.remove(temp_image_path)  # Clean up temp file

        if VISION_ERROR_PREFIX in vision_caption:
            raise HTTPException(status_code=500, detail=vision_caption)

        # Use LLM to get a response based on the caption
        llm_system_prompt = "You are an AI assistant that helps users understand what's on their screen. Provide a concise and helpful response based on the screen content."
        llm_user_prompt = f"Here's what's on the user's screen: {vision_caption}\nWhat should they do next?"
        llm_response = query_llm(llm_user_prompt, system_prompt=llm_system_prompt)

        # Reload TTS/Whisper models for future use
        logger.info("🔄 Reloading TTS/Whisper models after screen analysis")
        reload_models_if_needed()

        logger.info("✅ Screen analysis complete - all models restored")
        return {"commentary": vision_caption, "llm_response": llm_response}

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
            # Free VRAM for the vision model Ollama is about to load
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

            # Analyse the image with whatever vision model the user has installed
            vision_prompt = "Analyze this screen in detail. Describe what you see, including any text, UI elements, applications, and content visible."
            logger.info("🔍 Analyzing screen with the installed vision model...")

            try:
                vision_analysis = query_vision(temp_image_path, vision_prompt)
            except Exception as e:
                logger.error(f"Vision analysis failed: {e}")
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

            if VISION_ERROR_PREFIX in vision_analysis:
                raise HTTPException(status_code=500, detail=vision_analysis)

            # Additional cleanup before the LLM step
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
                        f"Screen analysis: {vision_analysis}\n\nPlease provide helpful insights about this screen.",
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
                            "content": f"Screen analysis: {vision_analysis}\n\nPlease provide helpful insights about this screen.",
                        },
                    ],
                    "stream": False,
                }

                logger.info(f"→ Asking inference backend with model {req.model}")
                headers = {"Content-Type": "application/json"}

                try:
                    resp = requests.post(
                        f"{VLLM_URL}/chat/completions",
                        json=payload,
                        headers=headers,
                        timeout=90,
                    )

                    if resp.status_code != 200:
                        logger.error(
                            "Inference backend error %s: %s",
                            resp.status_code,
                            resp.text,
                        )
                        raise HTTPException(
                            status_code=500,
                            detail=f"LLM request failed with status {resp.status_code}",
                        )

                    llm_response = (
                        resp.json()
                        .get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                        .strip()
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
                "screen_analysis": vision_analysis,
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
    Complete screen analysis with vision model + LLM response + TTS audio output.
    Implements intelligent model management: vision -> LLM -> TTS pipeline.
    """
    try:
        # Phase 1: free VRAM for the vision model Ollama is about to load
        logger.info(
            "🖼️ Phase 1: Starting screen analysis - clearing ALL GPU memory for vision"
        )
        unload_all_models()

        # Decode base64 image and save to a temporary file
        image_data = base64.b64decode(req.image.split(",")[1])
        temp_image_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.png")
        with open(temp_image_path, "wb") as f:
            f.write(image_data)

        # Analyse the image with whatever vision model the user has installed
        vision_prompt = "Analyze this screen comprehensively. Describe what you see, including any text, UI elements, applications, and content. Focus on what the user might need help with."
        logger.info("🔍 Analyzing screen with the installed vision model...")
        vision_analysis = query_vision(temp_image_path, vision_prompt)
        os.remove(temp_image_path)

        if VISION_ERROR_PREFIX in vision_analysis:
            raise HTTPException(status_code=500, detail=vision_analysis)

        # Phase 2: generate the LLM response
        logger.info("🤖 Phase 2: Generating LLM response")

        # Generate LLM response
        system_prompt = (
            req.system_prompt
            or "You are Harvis AI, an AI assistant. Based on the screen analysis, provide helpful, conversational insights. Keep responses under 100 words for voice output."
        )

        if req.model == "gemini-1.5-flash":
            llm_response = query_gemini(
                f"Screen analysis: {vision_analysis}\n\nProvide helpful insights about this screen.",
                [],
            )
        else:
            payload = {
                "model": req.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"Screen analysis: {vision_analysis}\n\nProvide helpful insights about this screen.",
                    },
                ],
                "stream": False,
            }
            headers = {"Content-Type": "application/json"}
            resp = requests.post(
                f"{VLLM_URL}/chat/completions",
                json=payload,
                headers=headers,
                timeout=90,
            )
            resp.raise_for_status()
            llm_response = (
                resp.json()
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

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

        # Use tts_engine from request if available, default to qwen
        tts_engine = getattr(req, "tts_engine", "qwen")
        sr, wav = safe_generate_speech_optimized(
            text=llm_response,
            audio_prompt=audio_prompt_path,
            exaggeration=req.exaggeration,
            temperature=req.temperature,
            cfg_weight=req.cfg_weight,
            tts_engine=tts_engine,
        )

        # Save audio file
        filename = f"screen_analysis_{uuid.uuid4()}.wav"
        filepath = os.path.join(tempfile.gettempdir(), filename)
        sf.write(filepath, wav, sr)

        logger.info("✅ Complete screen analysis with TTS finished")
        return {
            "response": llm_response,
            "screen_analysis": vision_analysis,
            "model_used": req.model,
            "audio_path": f"/api/audio/{filename}",
            "processing_stages": {
                "vision_analysis": "✅ Completed",
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
    model: str = Form(""),
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
    # The form default is empty, not a guessed tag — resolve it against what this
    # deployment actually serves.
    model = model or resolve_default_model()
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
        except TranscriptionUnavailable as e:
            # A provider setting, not a fault — 503 so the UI can tell the user
            # to use browser speech input instead of showing a server error.
            logger.warning(f"🎤 MIC-CHAT transcription unavailable: {e}")
            return JSONResponse(
                status_code=503,
                content={"status": "error", "error": str(e)},
            )
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
                elif is_moonshot_model(model):
                    # Use Moonshot/Kimi for voice chat
                    pool = getattr(app.state, "pg_pool", None)
                    if not pool:
                        return JSONResponse(
                            status_code=500,
                            content={
                                "status": "error",
                                "error": "Database not available",
                            },
                        )

                    moonshot_config = await get_user_api_key(
                        pool, current_user.id, "moonshot"
                    )
                    if not moonshot_config or not moonshot_config.get("api_key"):
                        return JSONResponse(
                            status_code=400,
                            content={
                                "status": "error",
                                "error": "Moonshot API key not configured",
                            },
                        )

                    try:
                        moonshot_client = MoonshotClient(
                            api_key=moonshot_config["api_key"],
                            base_url=moonshot_config.get("api_url")
                            or MOONSHOT_BASE_URL,
                        )

                        sys_prompt_path = os.path.join(
                            os.path.dirname(__file__), "system_prompt.txt"
                        )
                        try:
                            with open(sys_prompt_path, "r", encoding="utf-8") as f:
                                sys_prompt = f.read().strip()
                        except FileNotFoundError:
                            sys_prompt = 'You are "Jarves", a voice-first local assistant. Reply in ≤25 spoken-style words, sprinkling brief Spanish when natural.'

                        messages = [{"role": "system", "content": sys_prompt}]
                        for msg in history[:-1]:
                            messages.append(
                                {"role": msg["role"], "content": msg["content"]}
                            )
                        messages.append({"role": "user", "content": text})

                        moonshot_model_id = get_moonshot_model_id(model)
                        logger.info(
                            f"🎤 MIC-CHAT: Using Moonshot AI with model {moonshot_model_id}"
                        )

                        response_text = await moonshot_client.chat_completion(
                            model=moonshot_model_id, messages=messages
                        )

                    except Exception as e:
                        logger.error(f"🎤 MIC-CHAT: Moonshot request failed: {e}")
                        return JSONResponse(
                            status_code=500,
                            content={
                                "status": "error",
                                "error": f"Moonshot error: {str(e)}",
                            },
                        )
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
                        logger.debug(
                            f"[Low VRAM Mode] Skipping model unload for {model} — vLLM/llama-server manage memory automatically"
                        )

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
    async_research_agent_streaming,
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
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
):
    """
    Enhanced research chat endpoint with SSE streaming to prevent Nginx 499 timeouts.
    Streams progress updates during web searches and LLM inference.
    """

    # Resolve the cloud credential for THIS user before streaming research.
    #
    # The research agents are module-level singletons shared by every request, so
    # these setters must run unconditionally — including with an empty key. The
    # previous version only called them when a key was found, which meant the
    # singleton kept the LAST user's key: a second user with no Moonshot/NVIDIA
    # credential silently researched on the first user's account and quota, and
    # the missing-key branch downstream never fired because the global was still
    # populated. Clearing is the whole point of the unconditional call.
    if is_moonshot_model(req.model):
        from agent_research import set_research_agent_moonshot_key

        pool = getattr(request.app.state, "pg_pool", None)
        moonshot_config = (
            await get_user_api_key(pool, current_user.id, "moonshot") if pool else None
        ) or {}
        set_research_agent_moonshot_key(
            moonshot_config.get("api_key") or "",
            # api_url holds the platform verified at save time (.ai vs .cn).
            moonshot_config.get("api_url") or "",
        )

    if req.model == "nvidia-kimi":
        from agent_research import set_research_agent_nvidia_key

        pool = getattr(request.app.state, "pg_pool", None)
        nvidia_config = (
            await get_user_api_key(pool, current_user.id, "nvidia") if pool else None
        ) or {}
        set_research_agent_nvidia_key(nvidia_config.get("api_key") or "")

    # ── Live Web: dispatch through OpenClaw with unrestricted web access ──
    live_web = getattr(req, "live_web", False)
    if live_web:
        from workspace.workspace_router import launch_workspace_internal

        async def stream_live_research():
            yield f"data: {json.dumps({'status': 'starting', 'message': req.message, 'live_web': True})}\n\n"
            yield f"data: {json.dumps({'status': 'researching', 'detail': 'OpenClaw live web research active'})}\n\n"

            result = await launch_workspace_internal(
                request=request,
                user_id=current_user.id,
                task_brief=f"LIVE WEB RESEARCH: {req.message}",
                chat_history=req.history,
                agent_id="main",
                session_id=getattr(req, "session_id", None),
                live_web=True,
            )
            ws_id = result["workspace_id"]

            # Stream workspace events as SSE research progress
            from workspace.workspace_router import _workspace_broadcasters

            broadcaster = _workspace_broadcasters.get(ws_id)
            if not broadcaster:
                yield f"data: {json.dumps({'status': 'error', 'error': 'Failed to start live research workspace'})}\n\n"
                return

            live_queue = broadcaster.subscribe()
            try:
                final_content = ""
                while True:
                    try:
                        item = await asyncio.wait_for(live_queue.get(), timeout=300)
                    except asyncio.TimeoutError:
                        yield f"data: {json.dumps({'status': 'error', 'error': 'Live research timed out'})}\n\n"
                        return

                    if item is None:
                        break
                    seq, event = item
                    if event.type == "token":
                        token_text = event.data.get("token", "")
                        final_content += token_text
                        yield f"data: {json.dumps({'status': 'streaming', 'token': token_text})}\n\n"
                    elif event.type == "tool_call":
                        tool_name = event.data.get("name", "tool")
                        yield f"data: {json.dumps({'status': 'researching', 'detail': f'Using {tool_name}...', 'type': 'tool_call'})}\n\n"
                    elif event.type == "log":
                        msg = event.data.get("message", "")
                        yield f"data: {json.dumps({'status': 'researching', 'detail': msg})}\n\n"
                    elif event.type in ("done", "error"):
                        if event.type == "error":
                            err_msg = event.data.get("message", "Unknown error")
                            yield f"data: {json.dumps({'status': 'error', 'error': err_msg})}\n\n"
                            return
                        summary = event.data.get("summary", "") or final_content
                        final_content = summary
                        break

                # Emit final response
                yield f"data: {json.dumps({'status': 'complete', 'response': final_content, 'sources': [], 'live_web': True})}\n\n"
            finally:
                broadcaster.unsubscribe(live_queue)

        return StreamingResponse(
            stream_live_research(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

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
                    # Standard research with live streaming progress
                    logger.info(
                        f"[Research Chat] Starting streaming research for: {req.message}"
                    )

                    # Stream research progress events to frontend
                    async for event in async_research_agent_streaming(
                        req.message, req.model
                    ):
                        event_type = event.get("type")

                        if event_type == "search_query":
                            # Forward search query to frontend
                            query = event["query"]
                            yield f"data: {json.dumps({'status': 'researching', 'detail': f'Searching for: {query}', 'type': 'search_query', 'query': query})}\n\n"
                            logger.info(
                                f"[Research Chat] Streaming search query: {query}"
                            )

                        elif event_type == "search_result":
                            # Forward search result to frontend
                            title = event["title"]
                            yield f"data: {json.dumps({'status': 'researching', 'detail': f'Found: {title}', 'type': 'search_result', 'title': title, 'url': event['url'], 'domain': event['domain']})}\n\n"

                        elif event_type == "reading":
                            # Forward reading progress to frontend
                            domain = event["domain"]
                            yield f"data: {json.dumps({'status': 'researching', 'detail': f'Reading {domain}...', 'type': 'reading', 'domain': domain, 'url': event['url']})}\n\n"

                        elif event_type == "analysis":
                            # Forward analysis progress
                            yield f"data: {json.dumps({'status': 'researching', 'detail': event.get('detail', 'Analyzing...')})}\n\n"

                        elif event_type == "complete":
                            # Store final result
                            result_data = event.get("result", {})
                            analysis = result_data.get(
                                "analysis", "No analysis available"
                            )
                            sources = result_data.get("sources", [])
                            sources_found = result_data.get("sources_found", 0)
                            videos = result_data.get("videos", [])

                            response_content = f"{analysis}\n\n"
                            if sources:
                                response_content += (
                                    f"**Sources ({sources_found} found):**\n"
                                )
                                for i, source in enumerate(sources[:5], 1):
                                    title = source.get("title", "Unknown Title")
                                    url = source.get("url", "No URL")
                                    response_content += f"{i}. [{title}]({url})\n"
                            logger.info(
                                f"[Research Chat] Streaming research complete. Found {sources_found} sources"
                            )

                        elif event_type == "error":
                            response_content = (
                                f"Research Error: {event.get('error', 'Unknown error')}"
                            )

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
    model: str = Field(default_factory=_default_model_field)


class ComparativeResearchRequest(BaseModel):
    topics: List[str]
    model: str = Field(default_factory=_default_model_field)


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
    Fetches the list of available models from the configured provider (native
    Ollama API), vLLM, llama-server, and (optionally) the external Ollama
    endpoint.  Both local backends expose OpenAI /v1/models.

    When models are found the response stays a bare JSON array of names — the
    shape every existing caller parses.  When NOTHING answered, this returns
    HTTP 200 with an honest object instead of a 503:
        {"models": [], "provider_available": false, "reason": ..., "probed": [...]}
    so a box with no provider renders "no model provider configured" rather
    than an error, while a CONFIGURED provider being down stays distinguishable
    via the reason + per-probe errors.
    """
    ollama_model_names = []
    # Per-backend probe ledger, returned when everything came up empty so the
    # caller (and the operator reading the response) can see what was tried.
    probed: list[dict] = []

    # Fetch from the configured provider's native Ollama API
    try:
        ollama_base = LOCAL_OLLAMA_BASE_URL
        if "/v1" in ollama_base:
            ollama_tags_url = ollama_base.replace("/v1", "") + "/api/tags"
        else:
            ollama_tags_url = f"{ollama_base}/api/tags"
        logger.info(f"Trying to connect to local Ollama at: {ollama_tags_url}")
        response = requests.get(ollama_tags_url, timeout=10)
        if response.status_code == 200:
            models = response.json().get("models", [])
            local_ollama = [m["name"] for m in models]
            ollama_model_names.extend(local_ollama)
            # Track for chat routing back to Ollama
            for name in local_ollama:
                LOCAL_OLLAMA_MODELS_CACHE.add(name)
            logger.info(f"Available models from local Ollama: {local_ollama}")
            probed.append(
                {"provider": "ollama", "url": ollama_tags_url, "ok": True,
                 "models": len(local_ollama)}
            )
        else:
            logger.warning(f"Local Ollama returned status {response.status_code}")
            probed.append(
                {"provider": "ollama", "url": ollama_tags_url, "ok": False,
                 "error": f"HTTP {response.status_code}"}
            )
    except requests.exceptions.RequestException as e:
        logger.warning(f"Could not connect to local Ollama: {e}")
        probed.append(
            {"provider": "ollama", "url": ollama_tags_url, "ok": False,
             "error": str(e)[:200]}
        )

    # Fetch from vLLM (qwen3.5:9b)
    try:
        url = f"{VLLM_URL}/models"
        logger.info(f"Trying to connect to vLLM at: {url}")
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            models = response.json().get("data", [])
            local_models = [m["id"] for m in models if m["id"] not in ollama_model_names]
            ollama_model_names.extend(local_models)
            logger.info(f"Available models from vLLM: {local_models}")
            probed.append(
                {"provider": "vllm", "url": url, "ok": True, "models": len(local_models)}
            )
        else:
            logger.warning(f"vLLM returned status {response.status_code}")
            probed.append(
                {"provider": "vllm", "url": url, "ok": False,
                 "error": f"HTTP {response.status_code}"}
            )
    except requests.exceptions.RequestException as e:
        logger.warning(f"Could not connect to vLLM: {e}")
        probed.append(
            {"provider": "vllm", "url": url, "ok": False, "error": str(e)[:200]}
        )

    # Fetch from llama-server (devstral-24b)
    try:
        url = f"{LLAMA_URL}/models"
        logger.info(f"Trying to connect to llama-server at: {url}")
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            models = response.json().get("data", [])
            llama_models = [
                m["id"] for m in models if m["id"] not in ollama_model_names
            ]
            ollama_model_names.extend(llama_models)
            logger.info(f"Available models from llama-server: {llama_models}")
            probed.append(
                {"provider": "llama-server", "url": url, "ok": True,
                 "models": len(llama_models)}
            )
        else:
            logger.warning(f"llama-server returned status {response.status_code}")
            probed.append(
                {"provider": "llama-server", "url": url, "ok": False,
                 "error": f"HTTP {response.status_code}"}
            )
    except requests.exceptions.RequestException as e:
        logger.warning(f"Could not connect to llama-server: {e}")
        probed.append(
            {"provider": "llama-server", "url": url, "ok": False, "error": str(e)[:200]}
        )

    # Fetch from external Ollama (if configured — for large cloud-hosted models)
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

                for name in external_model_names:
                    EXTERNAL_MODELS_CACHE.add(name)

                for model_name in external_model_names:
                    if model_name not in ollama_model_names:
                        ollama_model_names.append(model_name)
                logger.info(
                    f"Available models from external Ollama: {external_model_names}"
                )
                logger.info(f"Updated EXTERNAL_MODELS_CACHE: {EXTERNAL_MODELS_CACHE}")
                probed.append(
                    {"provider": "external-ollama", "url": ext_url, "ok": True,
                     "models": len(external_model_names)}
                )
            else:
                logger.warning(
                    f"External Ollama returned status {ext_response.status_code}. Content: {ext_response.text[:200]}"
                )
                probed.append(
                    {"provider": "external-ollama", "url": ext_url, "ok": False,
                     "error": f"HTTP {ext_response.status_code}"}
                )
        except requests.exceptions.RequestException as e:
            logger.warning(f"Could not connect to external Ollama: {e}")
            # Do NOT fallback to hardcoded list since we want dynamic discovery only
            probed.append(
                {"provider": "external-ollama", "url": ext_url, "ok": False,
                 "error": str(e)[:200]}
            )

    # Add Gemini if configured
    if is_gemini_configured():
        ollama_model_names.insert(0, "gemini-1.5-flash")

    if not ollama_model_names:
        # HTTP 200, honestly empty — a box with no provider is a SUPPORTED state
        # (plug-and-play install), not a server error. A 503 here made the
        # frontend render an error where "no model provider configured" belongs.
        # The two empty cases stay distinguishable:
        #   • operator pointed HARVIS_LLM_BASE_URL/OLLAMA_URL somewhere → that
        #     provider is configured but unreachable/empty (a real fault);
        #   • base URL is still the default guess → nothing was configured.
        # `probed` carries the per-backend errors either way.
        if LLM_PROVIDER_EXPLICITLY_CONFIGURED or (
            EXTERNAL_OLLAMA_URL and EXTERNAL_OLLAMA_API_KEY
        ):
            reason = (
                f"configured model provider at {HARVIS_LLM_BASE_URL} is unreachable "
                "or reports no models — check that the server is running and the "
                "URL is correct"
            )
        else:
            reason = (
                "no model provider configured — start an Ollama/vLLM/llama-server "
                "instance and set HARVIS_LLM_BASE_URL (or OLLAMA_URL) to its address"
            )
        return {
            "models": [],
            "provider_available": False,
            "reason": reason,
            "probed": probed,
        }

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
    # Vision runs in Ollama now, so nothing is "loaded" in this process — what
    # matters to a caller is whether an image can be analysed at all.
    vision_available: bool
    total_models_loaded: int


class UnloadModelRequest(BaseModel):
    model_type: str  # "tts", "whisper", "all", "ollama"
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

    tts_loaded = tts_model is not None
    whisper_loaded = whisper_model is not None
    # Ollama owns the vision model's lifecycle, so report capability rather than
    # a load flag this process no longer has any say in.
    vision_available = bool(list_vision_models())

    total_loaded = sum([tts_loaded, whisper_loaded])

    return ModelStatusResponse(
        tts_loaded=tts_loaded,
        whisper_loaded=whisper_loaded,
        vision_available=vision_available,
        total_models_loaded=total_loaded,
    )


@app.post("/api/models/unload", tags=["model-management"])
async def unload_model(request: UnloadModelRequest):
    """Unload specific models to free memory"""
    from model_manager import unload_tts_model, unload_whisper_model, unload_models

    unloaded_models = []

    if request.model_type == "all":
        # Unload all models. Vision is not listed: it runs in Ollama, whose own
        # keep_alive owns that lifecycle (see model_type == "ollama" below).
        unload_models()
        unloaded_models = ["TTS", "Whisper"]

        # vLLM and llama-server manage memory automatically — no explicit unload needed
        if request.model_name:
            logger.debug(
                f"Skipping Ollama model unload for {request.model_name} — not applicable with vLLM/llama-server"
            )
            unloaded_models.append(f"InferenceBackend-{request.model_name}")

    elif request.model_type == "tts":
        unload_tts_model()
        unloaded_models.append("TTS")

    elif request.model_type == "whisper":
        unload_whisper_model()
        unloaded_models.append("Whisper")

    elif request.model_type == "ollama":
        if not request.model_name:
            raise HTTPException(
                400, "model_name required for inference backend model unloading"
            )

        # vLLM and llama-server manage memory automatically; nothing to unload
        logger.debug(
            f"Skipping Ollama/inference model unload for {request.model_name} — vLLM/llama-server manage memory automatically"
        )
        unloaded_models.append(f"InferenceBackend-{request.model_name}")

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
            tts_engine=req.tts_engine,
        )

        if sr is None or wav is None:
            raise HTTPException(500, f"TTS ({req.tts_engine}) generation failed")

        filename = f"response_{uuid.uuid4()}.wav"
        filepath = os.path.join(tempfile.gettempdir(), filename)
        sf.write(filepath, wav, sr)
        logger.info("Audio written to %s", filepath)

        return {"audio_path": f"/api/audio/{filename}", "tts_engine": req.tts_engine}

    except Exception as e:
        logger.exception("TTS synthesis endpoint crashed")
        raise HTTPException(500, str(e)) from e


@app.get("/api/tts-engines", tags=["tts"])
async def get_tts_engines():
    """
    Get list of available TTS engines.
    Returns information about each engine including VRAM requirements.
    """
    try:
        engines = get_available_tts_engines()
        active = get_active_tts_engine()
        return {
            "engines": engines,
            "active_engine": active,
            "default_engine": "qwen",
        }
    except Exception as e:
        logger.exception("Failed to get TTS engines")
        raise HTTPException(500, str(e)) from e


class SetTTSEngineRequest(BaseModel):
    engine: str  # "qwen" or "chatterbox"


@app.post("/api/tts-engine", tags=["tts"])
async def set_tts_engine(req: SetTTSEngineRequest):
    """
    Set the active TTS engine.
    """
    try:
        if req.engine not in ["chatterbox", "qwen"]:
            raise HTTPException(
                400, f"Invalid TTS engine: {req.engine}. Must be 'chatterbox' or 'qwen'"
            )

        set_active_tts_engine(req.engine)
        return {
            "success": True,
            "active_engine": req.engine,
            "message": f"TTS engine set to {req.engine}",
        }
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.exception("Failed to set TTS engine")
        raise HTTPException(500, str(e)) from e


# ═══════════════════════════════════════════════════════════════════════════════
# Background Job Queue Endpoints (Async TTS/Whisper)
# ═══════════════════════════════════════════════════════════════════════════════


class TTSJobRequest(BaseModel):
    """Request for async TTS job"""

    text: str
    voice_id: Optional[str] = None
    tts_engine: str = "qwen"


class WhisperJobRequest(BaseModel):
    """Request for async Whisper transcription job"""

    audio_path: str


@app.post("/api/jobs/tts", tags=["jobs"])
async def create_tts_job(
    req: TTSJobRequest, current_user: UserResponse = Depends(get_current_user)
):
    """
    Create an async TTS generation job.

    Returns immediately with job_id. Use /api/jobs/{job_id} to check status.
    This avoids HTTP timeouts for long-running TTS generation.
    """
    try:
        from job_queue import enqueue_tts_job

        job_id = await enqueue_tts_job(
            text=req.text,
            voice_id=req.voice_id,
            tts_engine=req.tts_engine,
            user_id=current_user.id if current_user else None,
        )

        return {
            "job_id": job_id,
            "status": "queued",
            "message": "TTS job queued successfully. Check /api/jobs/{job_id} for status.",
        }

    except Exception as e:
        logger.exception("Failed to create TTS job")
        raise HTTPException(500, f"Failed to create TTS job: {str(e)}") from e


@app.post("/api/jobs/whisper", tags=["jobs"])
async def create_whisper_job(
    req: WhisperJobRequest, current_user: UserResponse = Depends(get_current_user)
):
    """
    Create an async Whisper transcription job.

    Returns immediately with job_id. Use /api/jobs/{job_id} to check status.
    This avoids HTTP timeouts for long-running transcription.
    """
    try:
        from job_queue import enqueue_whisper_job

        job_id = await enqueue_whisper_job(
            audio_path=req.audio_path, user_id=current_user.id if current_user else None
        )

        return {
            "job_id": job_id,
            "status": "queued",
            "message": "Whisper job queued successfully. Check /api/jobs/{job_id} for status.",
        }

    except Exception as e:
        logger.exception("Failed to create Whisper job")
        raise HTTPException(500, f"Failed to create Whisper job: {str(e)}") from e


@app.get("/api/jobs/{job_id}", tags=["jobs"])
async def get_job_status(
    job_id: str, current_user: UserResponse = Depends(get_current_user)
):
    """
    Get the status of a background job.

    Returns job state: 'created', 'active', 'completed', 'failed', etc.
    For completed jobs, includes result data (audio_path, text, etc.)
    """
    try:
        from job_queue import get_job_queue

        queue = await get_job_queue()
        status = await queue.get_job_status(job_id)

        if not status:
            raise HTTPException(404, f"Job {job_id} not found")

        return status

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get job status for {job_id}")
        raise HTTPException(500, f"Failed to get job status: {str(e)}") from e


class ResearchStatsResponse(BaseModel):
    """Response model for research stats endpoint"""

    pipeline_stats: dict
    cache_stats: dict
    system_info: dict


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


# ─── Job Queue Endpoints ─────────────────────────────────────────────────────
# These endpoints allow the frontend to enqueue jobs for async processing

from pydantic import BaseModel
from typing import Dict, Any


class EnqueueJobRequest(BaseModel):
    name: str
    data: Dict[str, Any]
    retry_limit: int = 3
    priority: int = 0


@app.post("/api/jobs/enqueue", tags=["jobs"])
async def enqueue_job(request: EnqueueJobRequest):
    """
    Enqueue a job for async processing
    This is called by the frontend to create a background job
    """
    try:
        from job_queue import get_job_queue

        queue = await get_job_queue()
        job_id = await queue.send(
            name=request.name,
            data=request.data,
            retry_limit=request.retry_limit,
            priority=request.priority,
        )

        logger.info(f"📨 Job enqueued via API: {request.name} (id: {job_id})")

        return {"job_id": job_id, "status": "queued", "queue": request.name}

    except Exception as e:
        logger.error(f"Error enqueuing job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to enqueue job: {str(e)}")


@app.get("/api/jobs/{job_id}/status", tags=["jobs"])
async def get_job_status(job_id: str):
    """
    Get the status of a job
    """
    try:
        from job_queue import get_job_queue

        queue = await get_job_queue()
        status = await queue.get_job_status(job_id)

        if not status:
            raise HTTPException(status_code=404, detail="Job not found")

        return status

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get job status: {str(e)}"
        )


# ─── Startup and Shutdown Events ─────────────────────────────────────────────


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    try:
        # Initialize job queue
        from job_queue import init_job_queue

        await init_job_queue()
        logger.info("✅ Job queue initialized on startup")
        
        # Initialize OpenClaw LLM config table
        pool = getattr(app.state, "pg_pool", None)
        if pool:
            async with pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS openclaw_llm_config (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                        provider_url VARCHAR(500) NOT NULL,
                        api_key_encrypted TEXT,
                        model_id VARCHAR(255) NOT NULL,
                        provider_type VARCHAR(50) DEFAULT 'openai',
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(user_id)
                    )
                """)
                # Per-user workspace ENGINE preference (separate from the model):
                # 'native' = OpenClaw tool loop, 'claude-code' = Claude Code direct engine.
                await conn.execute(
                    "ALTER TABLE openclaw_llm_config "
                    "ADD COLUMN IF NOT EXISTS engine TEXT DEFAULT 'native'"
                )
                # Last LOCAL model the user picked — restored as the fallback when
                # a cloud model can't drive the OpenClaw workspace.
                await conn.execute(
                    "ALTER TABLE openclaw_llm_config "
                    "ADD COLUMN IF NOT EXISTS last_local_model_id TEXT"
                )
                # Per-user multi-agent (orchestrate) opt-in for Discord workspaces.
                await conn.execute(
                    "ALTER TABLE openclaw_llm_config "
                    "ADD COLUMN IF NOT EXISTS orchestrate_enabled BOOLEAN DEFAULT FALSE"
                )
                logger.info("✅ OpenClaw LLM config table initialized")
    except Exception as e:
        logger.error(f"Failed to initialize job queue: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    try:
        # Shutdown job queue
        from job_queue import shutdown_job_queue

        await shutdown_job_queue()
        logger.info("🛑 Job queue shutdown")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


# ─── Vibe Coding Endpoints ─────────────────────────────────────────────────────

# Vibe coding endpoint moved to vibecoding.commands

# Voice transcribe endpoint moved to vibecoding.commands

# Run command endpoint moved to vibecoding.commands

# Save file endpoint moved to vibecoding.commands

# ─── Vibe Agent Helper Functions moved to vibecoding.core ─────────────────────
